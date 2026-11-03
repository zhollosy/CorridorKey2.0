"""Background execution: the job queue, one-off tool commands and GPU polling.

Worker threads never touch Tk. They post tuples to an event queue that the
main window drains with ``after()``.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import threading
import time

from .config import Preferences
from .jobs import Job, build_command, command_line, output_dir_for, validate

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


LOW_CACHE_SPACE_GB = 8.0


def free_space_gb(path: str) -> float | None:
    """Free space on the drive holding ``path`` (or its nearest existing parent)."""
    probe = os.path.abspath(path)
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            return None
        probe = parent
    try:
        return shutil.disk_usage(probe).free / 1e9
    except OSError:
        return None


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, creationflags=CREATE_NO_WINDOW)
    else:
        proc.kill()


class ProgressParser:
    """Turn infer.py log lines into (percent, stage) updates."""

    STEPS = (
        (re.compile(r"Loading CorridorKey"), 2, "Loading model"),
        (re.compile(r"probed (\d+) frames"), 8, "Probing input"),
        (re.compile(r"Auto VRAM:"), 10, "Selecting memory profile"),
        (re.compile(r"RVM continuous prepass"), 12, "RVM prepass"),
        (re.compile(r"frozen VFM prepass"), 18, "Foundation prepass"),
        (re.compile(r"Hann stage1:.*windows=(\d+)"), 20, "Stage 1 / 2"),
    )
    WINDOW = re.compile(r"window (\d+)/(\d+)")
    DONE = re.compile(r"wrote \d+ output")

    def parse(self, line: str):
        m = self.WINDOW.search(line)
        if m:
            i, n = int(m.group(1)), max(1, int(m.group(2)))
            # A window's output is written while the next window runs.
            return 20 + 78 * (i - 1) / n, f"Window {i}/{n}"
        if self.DONE.search(line):
            return 100.0, "Finished"
        for pattern, pct, stage in self.STEPS:
            if pattern.search(line):
                return float(pct), stage
        return None


class QueueRunner:
    """Runs enabled, queued jobs one after another in a worker thread."""

    def __init__(self, events: queue.Queue):
        self.events = events
        self._thread = None
        self._proc = None
        self._abort = threading.Event()
        self._stop_after_current = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, next_job, prefs: Preferences) -> None:
        """Start the worker. ``next_job()`` returns the next Job to render or None.

        It is called again after every job, so jobs queued mid-run are picked up.
        """
        if self.running:
            return
        self._abort.clear()
        self._stop_after_current.clear()
        self._thread = threading.Thread(target=self._run, args=(next_job, prefs), daemon=True)
        self._thread.start()

    def stop_after_current(self) -> None:
        self._stop_after_current.set()

    def abort(self) -> None:
        self._abort.set()
        proc = self._proc
        if proc is not None:
            kill_tree(proc)

    def _emit(self, *event) -> None:
        self.events.put(event)

    def _run(self, next_job, prefs: Preferences) -> None:
        summary = {"Done": 0, "Failed": 0, "Cancelled": 0, "Skipped": 0}
        t_queue = time.time()
        while not (self._abort.is_set() or self._stop_after_current.is_set()):
            job = next_job()
            if job is None:
                break
            status = self._run_job(job, prefs)
            summary[status] = summary.get(status, 0) + 1
            if self._abort.is_set():
                break
        self._proc = None
        self._emit("queue_done", summary, time.time() - t_queue)

    def _run_job(self, job: Job, prefs: Preferences) -> str:
        error = validate(job)
        if error:
            self._emit("log", job.id, f"[ERROR] {job.name}: {error}", "error")
            self._emit("status", job.id, "Failed", 0.0, error)
            return "Failed"

        out_dir = output_dir_for(job, prefs)
        if prefs.skip_existing and os.path.isdir(out_dir) and any(
                n.startswith(job.name + "_") and not n.endswith("_settings.txt")
                for n in os.listdir(out_dir)):
            self._emit("log", job.id, f"Skipping {job.name}: outputs already exist in {out_dir}", "warn")
            self._emit("status", job.id, "Skipped", 100.0, "Outputs exist")
            return "Skipped"

        cmd = build_command(job, prefs)
        self._emit("log", job.id, f"\n=== {job.name} ===", "header")
        self._emit("log", job.id, "$ " + command_line(cmd), "cmd")
        self._emit("status", job.id, "Running", 0.0, "Starting", out_dir)
        free = free_space_gb(prefs.temp_dir)
        if free is not None and free < LOW_CACHE_SPACE_GB:
            self._emit("log", job.id,
                       f"[WARNING] Only {free:.1f} GB free for the feature cache at {prefs.temp_dir}. "
                       "Long or high-resolution clips need several GB - set Preferences > General > "
                       "Feature cache folder to a drive with more space.", "warn")

        parser = ProgressParser()
        tail = []
        t0 = time.time()
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=_child_env(),
                cwd=os.path.dirname(prefs.resolved_infer_script()),
                creationflags=CREATE_NO_WINDOW)
        except OSError as exc:
            self._emit("log", job.id, f"[ERROR] could not start worker: {exc}", "error")
            self._emit("status", job.id, "Failed", 0.0, str(exc))
            return "Failed"

        for raw in self._proc.stdout:
            for line in raw.replace("\r", "\n").splitlines():
                if not line.strip():
                    continue
                tail = (tail + [line])[-30:]
                low = line.lower()
                tag = ("error" if ("error" in low or "traceback" in low)
                       else "warn" if "warning" in low else None)
                self._emit("log", job.id, line, tag)
                update = parser.parse(line)
                if update:
                    self._emit("progress", job.id, update[0], update[1], time.time() - t0)
        code = self._proc.wait()
        elapsed = time.time() - t0

        if self._abort.is_set():
            self._emit("status", job.id, "Cancelled", 0.0, "Aborted by user", out_dir, elapsed)
            return "Cancelled"
        if code == 0:
            self._emit("status", job.id, "Done", 100.0, "Finished", out_dir, elapsed)
            return "Done"
        reason = next((l for l in reversed(tail) if "Error" in l or "error" in l), f"exit code {code}")
        tail_text = "\n".join(tail).lower()
        if "out of memory" in tail_text:
            reason = "CUDA out of memory - try manual memory mode with Low VRAM and a smaller window"
        elif "no space left on device" in tail_text or "errno 28" in tail_text:
            reason = (f"Disk full while writing the feature cache ({prefs.temp_dir}) or outputs - "
                      "set Preferences > General > Feature cache folder to a drive with more space")
        self._emit("status", job.id, "Failed", 0.0, reason.strip(), out_dir, elapsed)
        return "Failed"


class ToolRunner:
    """Runs a single helper command (environment check, weight download...)."""

    def __init__(self, events: queue.Queue):
        self.events = events
        self._thread = None
        self._proc = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, title: str, cmd: list[str], cwd: str) -> bool:
        if self.running:
            return False
        self._thread = threading.Thread(target=self._run, args=(title, cmd, cwd), daemon=True)
        self._thread.start()
        return True

    def abort(self) -> None:
        if self._proc is not None:
            kill_tree(self._proc)

    def _run(self, title, cmd, cwd):
        self.events.put(("log", None, f"\n=== {title} ===", "header"))
        self.events.put(("log", None, "$ " + command_line(cmd), "cmd"))
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=_child_env(), cwd=cwd,
                creationflags=CREATE_NO_WINDOW)
        except OSError as exc:
            self.events.put(("log", None, f"[ERROR] {exc}", "error"))
            self.events.put(("tool_done", title, -1))
            return
        for raw in self._proc.stdout:
            for line in raw.replace("\r", "\n").splitlines():
                if line.strip():
                    low = line.lower()
                    tag = "error" if "error" in low else "warn" if "warn" in low else None
                    self.events.put(("log", None, line, tag))
        code = self._proc.wait()
        self._proc = None
        self.events.put(("tool_done", title, code))


class GpuMonitor:
    """Polls nvidia-smi in the background and posts ('gpu', info|None)."""

    def __init__(self, events: queue.Queue, interval: float = 2.0):
        self.events = events
        self.interval = max(1.0, float(interval))
        self._stop = threading.Event()
        self._smi = shutil.which("nvidia-smi")
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        if self._smi:
            self._thread.start()
        else:
            self.events.put(("gpu", None))

    def stop(self):
        self._stop.set()

    def _run(self):
        query = ["--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                 "--format=csv,noheader,nounits"]
        while not self._stop.is_set():
            try:
                out = subprocess.run([self._smi, *query], capture_output=True, text=True,
                                     timeout=5, creationflags=CREATE_NO_WINDOW).stdout
                name, used, total, util, temp = [p.strip() for p in out.splitlines()[0].split(",")]
                self.events.put(("gpu", {"name": name, "used": int(used), "total": int(total),
                                         "util": int(util), "temp": int(temp)}))
            except Exception:
                self.events.put(("gpu", None))
            self._stop.wait(self.interval)


ENV_CHECK_SCRIPT = r'''
import shutil, sys
from pathlib import Path
root = Path.cwd()
ok = True
def report(label, good, detail=""):
    global ok
    ok &= bool(good)
    print(f"[{'OK' if good else 'FAIL'}] {label}{(': ' + detail) if detail else ''}")
print(f"Python {sys.version.split()[0]} at {sys.executable}")
try:
    import torch
    report("PyTorch", True, torch.__version__)
    cuda = torch.cuda.is_available()
    report("CUDA available", cuda, torch.cuda.get_device_name(0) if cuda else "no CUDA device")
    if cuda:
        free, total = torch.cuda.mem_get_info()
        report("GPU memory", True, f"{free/1e9:.1f} GB free of {total/1e9:.1f} GB")
except Exception as exc:
    report("PyTorch", False, str(exc))
for mod in ("cv2", "transformers", "timm", "safetensors", "utils3d", "einops", "scipy"):
    try:
        __import__(mod)
        report(f"module {mod}", True)
    except Exception as exc:
        report(f"module {mod}", False, str(exc))
ff = shutil.which(sys.argv[1] if len(sys.argv) > 1 else "ffmpeg")
report("ffmpeg", ff is not None, ff or "not found on PATH")
for rel in ("weights/corridorkey_v2.safetensors", "weights/foundation_stats.safetensors",
            "vfms/moge/model.pt", "vfms/rvm/pretrain_rvm_small16_256_204031069.npz",
            "vfms/cradio/C-RADIOv4-SO400M/model.safetensors"):
    p = root / rel
    report(rel, p.is_file(), f"{p.stat().st_size/1e9:.2f} GB" if p.is_file() else "missing - run Tools > Download Weights")
print("\nEnvironment looks good." if ok else "\nSome checks failed - see above.")
'''

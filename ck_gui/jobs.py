"""Job model, input discovery and infer.py command building."""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .config import Preferences

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".mxf", ".m4v"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".webp", ".dpx"}
HINT_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".exr"}
ALL_OUTPUTS = ("alpha", "fg", "checker", "cutout")

HINT_MODES = {
    "none": "No hint",
    "first_frame": "First-frame hint",
    "video": "Hint video",
}


@dataclass
class JobSettings:
    hint_mode: str = "none"
    hint_first_frame: str = ""
    hint_video: str = ""
    hint_quality: float = 0.95
    carry_hint: bool = True
    carry_hint_quality: float = 0.95
    outputs: list = field(default_factory=lambda: ["alpha", "fg"])
    output_format: str = "video"
    despill_strength: float = 0.5
    cutout_linear: bool = False
    memory_mode: str = "auto"  # auto | manual
    hann_chunk: int = 24
    hann_stride: int = 12
    low_vram: bool = False
    num_frames: int = -1
    start_mode: str = "begin"
    seed: int = 0
    frame_dir_fps: float = 24.0
    frame_dir_linear: bool = False
    model_scale: float = 1.0
    linear_brightness: float = 1.0
    linear_contrast: float = 1.0
    linear_contrast_pivot: float = 0.18
    output_dir: str = ""  # empty = derived from preferences

    def copy(self) -> "JobSettings":
        return JobSettings.from_dict(self.to_dict())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "JobSettings":
        known = {f.name for f in fields(cls)}
        obj = cls()
        for key, value in (data or {}).items():
            if key in known:
                setattr(obj, key, list(value) if key == "outputs" else value)
        return obj


@dataclass
class Job:
    input_path: str
    settings: JobSettings = field(default_factory=JobSettings)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    status: str = "Queued"  # Queued | Running | Done | Failed | Cancelled | Skipped
    progress: float = 0.0
    stage: str = ""
    elapsed: float = 0.0
    output_dir_used: str = ""
    enabled: bool = True

    @property
    def name(self) -> str:
        return clip_name(self.input_path)

    @property
    def kind(self) -> str:
        return "Sequence" if Path(self.input_path).is_dir() else "Video"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["settings"] = self.settings.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        job = cls(input_path=data["input_path"],
                  settings=JobSettings.from_dict(data.get("settings", {})))
        for key in ("status", "progress", "elapsed", "output_dir_used", "enabled"):
            if key in data:
                setattr(job, key, data[key])
        if job.status == "Running":
            job.status, job.progress = "Queued", 0.0
        return job


def clip_name(path: str) -> str:
    """Mirror corridorkey.video_io.raw_clip_name so output files can be found."""
    norm = os.path.normpath(str(path))
    name = os.path.splitext(os.path.basename(norm))[0]
    if name.lower() in {"input", "frames", "rgb"}:
        return os.path.basename(os.path.dirname(norm)) or name
    return name


def mode_label(job: Job) -> str:
    return HINT_MODES.get(job.settings.hint_mode, job.settings.hint_mode)


# ----------------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------------

def _has_files(folder: Path, exts) -> bool:
    try:
        return any(p.is_file() and p.suffix.lower() in exts for p in folder.iterdir())
    except OSError:
        return False


def sequence_layout(folder: Path):
    """Return (frames_dir, hint_dir) for a frame-sequence folder, else (None, None).

    Supports a folder of frames directly, or the launcher convention of an
    ``Input`` subfolder with an optional ``AlphaHint`` subfolder.
    """
    if not folder.is_dir():
        return None, None
    input_dir = hint_dir = None
    try:
        for item in folder.iterdir():
            if item.is_dir():
                low = item.name.lower()
                if low == "input":
                    input_dir = item
                elif low == "alphahint":
                    hint_dir = item
    except OSError:
        return None, None
    if input_dir is not None and _has_files(input_dir, IMAGE_EXTS):
        return input_dir, hint_dir
    # A folder that holds video files is a batch folder, even if stray images sit next to them.
    if _has_files(folder, IMAGE_EXTS) and not _has_files(folder, VIDEO_EXTS):
        return folder, None
    return None, None


def find_hint_video(path: Path):
    stem = path.stem.lower() + "_alphahint"
    for item in sorted(path.parent.iterdir()):
        if (item.is_file() and item.suffix.lower() in VIDEO_EXTS
                and item.name.lower().startswith(stem)):
            return item
    return None


def find_frame_hint(path: Path):
    base = path.stem.lower()
    frame_hints, legacy = [], []
    for item in sorted(path.parent.iterdir()):
        if not item.is_file() or item.suffix.lower() not in HINT_IMAGE_EXTS:
            continue
        low = item.stem.lower()
        if not low.startswith(base):
            continue
        rest = low[len(base):].lstrip("_- ")
        if rest.startswith("framehint"):
            frame_hints.append(item)
        elif rest.startswith("alphahint"):
            legacy.append(item)
    hits = frame_hints or legacy
    return hits[0] if hits else None


def is_hint_file(path: Path) -> bool:
    low = path.stem.lower()
    return "_alphahint" in low or low.endswith("framehint")


def make_job(path: Path, defaults: JobSettings, auto_hints: bool) -> Job | None:
    path = Path(path)
    settings = defaults.copy()
    settings.hint_first_frame = settings.hint_video = ""
    settings.hint_mode = "none"
    if path.is_dir():
        frames_dir, hint_dir = sequence_layout(path)
        if frames_dir is None:
            return None
        if auto_hints:
            if hint_dir is not None:
                settings.hint_mode, settings.hint_video = "video", str(hint_dir)
            else:
                hint = find_frame_hint(path)
                if hint is not None:
                    settings.hint_mode, settings.hint_first_frame = "first_frame", str(hint)
        return Job(input_path=str(frames_dir), settings=settings)
    if path.suffix.lower() not in VIDEO_EXTS or is_hint_file(path):
        return None
    if auto_hints:
        video_hint = find_hint_video(path)
        frame_hint = find_frame_hint(path)
        if video_hint is not None:
            settings.hint_mode, settings.hint_video = "video", str(video_hint)
        elif frame_hint is not None:
            settings.hint_mode, settings.hint_first_frame = "first_frame", str(frame_hint)
    return Job(input_path=str(path), settings=settings)


def discover(paths, defaults: JobSettings, auto_hints: bool) -> list[Job]:
    """Turn dropped/selected paths into jobs. Folders are scanned one level deep."""
    jobs = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            frames_dir, _ = sequence_layout(path)
            if frames_dir is not None:
                job = make_job(path, defaults, auto_hints)
                if job:
                    jobs.append(job)
                continue
            try:
                children = sorted(path.iterdir())
            except OSError:
                continue
            for child in children:
                job = make_job(child, defaults, auto_hints)
                if job:
                    jobs.append(job)
        elif path.is_file():
            job = make_job(path, defaults, auto_hints)
            if job:
                jobs.append(job)
    seen, unique = set(), []
    for job in jobs:
        key = os.path.normcase(os.path.abspath(job.input_path))
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


# ----------------------------------------------------------------------------
# Command building
# ----------------------------------------------------------------------------

def output_dir_for(job: Job, prefs: Preferences) -> str:
    if job.settings.output_dir:
        return job.settings.output_dir
    src = Path(job.input_path)
    folder_name = prefs.output_pattern.format(name=job.name) or f"out_{job.name}"
    if prefs.output_location == "custom_root" and prefs.output_root:
        return str(Path(prefs.output_root) / folder_name)
    parent = src.parent
    if src.is_dir() and src.name.lower() == "input":
        parent = parent.parent
    return str(parent / folder_name)


def build_command(job: Job, prefs: Preferences) -> list[str]:
    s = job.settings
    cmd = [prefs.resolved_python(), "-u", prefs.resolved_infer_script(),
           "--input", job.input_path,
           "--output_dir", output_dir_for(job, prefs)]

    if s.hint_mode == "first_frame" and s.hint_first_frame:
        cmd += ["--hint_first_frame", s.hint_first_frame]
    elif s.hint_mode == "video" and s.hint_video:
        cmd += ["--hint_video", s.hint_video]
    if s.hint_mode != "none":
        cmd += ["--hint_quality", f"{s.hint_quality:g}"]
    if s.carry_hint:
        cmd += ["--carry_hint_quality", f"{s.carry_hint_quality:g}"]
    else:
        cmd += ["--no_carry_hint"]

    outputs = [o for o in ALL_OUTPUTS if o in s.outputs] or ["alpha", "fg"]
    cmd += ["--outputs", *outputs]
    cmd += ["--output_format", s.output_format]
    if s.output_format == "exr":
        cmd += ["--exr_dtype", prefs.exr_dtype]
    cmd += ["--despill_strength", f"{s.despill_strength:g}"]
    if s.cutout_linear:
        cmd += ["--cutout_linear"]

    if s.memory_mode == "manual":
        cmd += ["--hann_chunk", str(int(s.hann_chunk)),
                "--hann_stride", str(int(s.hann_stride))]
        if s.low_vram:
            cmd += ["--low_vram"]
    cmd += ["--temp_dir", prefs.temp_dir]

    if int(s.num_frames) > 0:
        cmd += ["--num_frames", str(int(s.num_frames)), "--start_mode", s.start_mode]
        if s.start_mode == "random_middle":
            cmd += ["--seed", str(int(s.seed))]
    if job.kind == "Sequence":
        cmd += ["--frame_dir_fps", f"{s.frame_dir_fps:g}"]
        if s.frame_dir_linear:
            cmd += ["--frame_dir_linear"]
    if s.model_scale != 1.0:
        cmd += ["--model_scale", f"{s.model_scale:g}"]
    if (s.linear_brightness, s.linear_contrast, s.linear_contrast_pivot) != (1.0, 1.0, 0.18):
        cmd += ["--linear_brightness", f"{s.linear_brightness:g}",
                "--linear_contrast", f"{s.linear_contrast:g}",
                "--linear_contrast_pivot", f"{s.linear_contrast_pivot:g}"]

    cmd += ["--ffmpeg_bin", prefs.ffmpeg_bin,
            "--ffmpeg_codec", prefs.ffmpeg_codec,
            "--crf", str(int(prefs.crf)),
            "--preset", prefs.preset,
            "--pix_fmt", prefs.pix_fmt,
            "--ffmpeg_threads", str(int(prefs.ffmpeg_threads)),
            "--stage2_batch", str(int(prefs.stage2_batch))]
    if prefs.bitrate:
        cmd += ["--bitrate", prefs.bitrate]
    if s.memory_mode == "manual" and s.low_vram:
        cmd += ["--low_vram_foundation_chunk", str(prefs.low_vram_foundation_chunk),
                "--low_vram_mlp_chunk_tokens", str(prefs.low_vram_mlp_chunk_tokens),
                "--low_vram_enc_frame_chunk", str(prefs.low_vram_enc_frame_chunk),
                "--low_vram_swin_window_batch", str(prefs.low_vram_swin_window_batch),
                "--low_vram_full_attn_query_chunk_tokens",
                str(prefs.low_vram_full_attn_query_chunk_tokens)]
    return cmd


def command_line(cmd: list[str]) -> str:
    return subprocess.list2cmdline(cmd)


def validate(job: Job) -> str | None:
    """Return an error message if the job cannot run, else None."""
    if not os.path.exists(job.input_path):
        return f"Input not found: {job.input_path}"
    s = job.settings
    if s.hint_mode == "first_frame" and not os.path.exists(s.hint_first_frame or ""):
        return "First-frame hint file is missing."
    if s.hint_mode == "video" and not os.path.exists(s.hint_video or ""):
        return "Hint video is missing."
    if not any(o in s.outputs for o in ALL_OUTPUTS):
        return "No outputs selected."
    if s.memory_mode == "manual" and (int(s.hann_chunk) < 1 or int(s.hann_stride) < 1):
        return "Hann chunk and stride must be at least 1."
    return None


def find_outputs(job: Job, prefs: Preferences) -> dict[str, str]:
    """Map output label -> path for files this job has written."""
    out_dir = Path(job.output_dir_used or output_dir_for(job, prefs))
    found = {}
    if not out_dir.is_dir():
        return found
    prefix = job.name + "_"
    for item in sorted(out_dir.iterdir()):
        if not item.name.startswith(prefix):
            continue
        label = item.name[len(prefix):]
        kind = label.split("_")[0].split(".")[0]
        if kind not in ALL_OUTPUTS:
            continue
        if item.is_file() and item.suffix.lower() in VIDEO_EXTS:
            found[kind] = str(item)
        elif item.is_dir() and label.endswith("_exr"):
            found[f"{kind} (EXR)"] = str(item)
    return found


def save_queue(path, jobs: list[Job]) -> None:
    payload = {"version": 1, "jobs": [j.to_dict() for j in jobs]}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_queue(path) -> list[Job]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Job.from_dict(d) for d in data.get("jobs", [])]

"""Persistent preferences and UI state for CorridorKey Studio."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "CorridorKey Studio"
APP_VERSION = "1.0.0"

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "CorridorKeyStudio"
CONFIG_FILE = CONFIG_DIR / "config.json"
LAST_QUEUE_FILE = CONFIG_DIR / "last_queue.json"


def _from_dict(cls, data: dict):
    """Build a dataclass from a dict, ignoring unknown keys and bad types."""
    known = {f.name: f for f in fields(cls)}
    kwargs = {}
    for key, value in (data or {}).items():
        if key in known:
            kwargs[key] = value
    try:
        return cls(**kwargs)
    except TypeError:
        return cls()


@dataclass
class Preferences:
    # General
    python_exe: str = ""
    infer_script: str = ""
    temp_dir: str = str(Path(tempfile.gettempdir()) / "corridorkey_v2")
    output_location: str = "next_to_clip"  # next_to_clip | custom_root
    output_root: str = ""
    output_pattern: str = "out_{name}"
    skip_existing: bool = False
    auto_detect_hints: bool = True
    restore_queue: bool = True
    open_output_when_done: bool = False
    sound_on_finish: bool = True
    confirm_exit_while_running: bool = True
    # Encoding
    ffmpeg_bin: str = "ffmpeg"
    ffmpeg_codec: str = "libx264"
    crf: int = 12
    preset: str = "medium"
    pix_fmt: str = "yuv444p10le"
    bitrate: str = ""
    ffmpeg_threads: int = 2
    exr_dtype: str = "half"
    # Performance
    stage2_batch: int = 1
    low_vram_foundation_chunk: int = 4
    low_vram_mlp_chunk_tokens: int = 65536
    low_vram_enc_frame_chunk: int = 1
    low_vram_swin_window_batch: int = 16
    low_vram_full_attn_query_chunk_tokens: int = 2048
    gpu_poll_seconds: int = 2
    # Appearance
    theme: str = "dark"
    log_font_size: int = 9
    max_log_lines: int = 5000

    def resolved_python(self) -> str:
        if self.python_exe and Path(self.python_exe).is_file():
            return self.python_exe
        for candidate in (REPO_ROOT / "venv" / "Scripts" / "python.exe",
                          REPO_ROOT / ".venv" / "Scripts" / "python.exe",
                          REPO_ROOT / "venv" / "bin" / "python"):
            if candidate.is_file():
                return str(candidate)
        exe = Path(sys.executable)
        # Never launch workers through pythonw: their output would be lost.
        if exe.name.lower() == "pythonw.exe":
            exe = exe.with_name("python.exe")
        return str(exe)

    def resolved_infer_script(self) -> str:
        if self.infer_script and Path(self.infer_script).is_file():
            return self.infer_script
        return str(REPO_ROOT / "infer.py")


@dataclass
class UIState:
    geometry: str = "1500x900"
    zoomed: bool = False
    recent_queues: list = field(default_factory=list)
    last_dir: str = ""
    show_log: bool = True
    show_preview: bool = True
    defaults: dict = field(default_factory=dict)


class Config:
    def __init__(self):
        self.prefs = Preferences()
        self.state = UIState()

    def load(self) -> "Config":
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self
        self.prefs = _from_dict(Preferences, data.get("preferences", {}))
        self.state = _from_dict(UIState, data.get("state", {}))
        return self

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"preferences": asdict(self.prefs), "state": asdict(self.state)}
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_FILE)

    def add_recent(self, path: str, limit: int = 8) -> None:
        path = str(path)
        recent = [p for p in self.state.recent_queues if p != path]
        self.state.recent_queues = [path] + recent[: limit - 1]

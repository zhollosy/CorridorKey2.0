"""Frame reading and the preview/compare panel."""
from __future__ import annotations

import os

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from .jobs import IMAGE_EXTS


class FrameSource:
    """Random access to frames of a video file or an image-sequence folder."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._cap = None
        self._files = []
        self.fps = 24.0
        self.width = self.height = 0
        if os.path.isdir(path):
            self._files = sorted(str(p) for p in Path(path).iterdir()
                                 if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
            self.frame_count = len(self._files)
            first = self.read(0) if self._files else None
            if first is not None:
                self.height, self.width = first.shape[:2]
        else:
            self._cap = cv2.VideoCapture(path)
            self.frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self.fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 24.0)
            self.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self._pos = -1

    @property
    def ok(self) -> bool:
        return self.frame_count > 0

    def info(self) -> str:
        if not self.ok:
            return "unreadable"
        dur = self.frame_count / self.fps if self.fps else 0
        return f"{self.width}x{self.height}  {self.fps:.3g} fps  {self.frame_count} frames  {dur:.1f}s"

    def read(self, index: int):
        """Return frame ``index`` as RGB uint8, or None."""
        index = max(0, min(int(index), max(0, self.frame_count - 1)))
        with self._lock:
            if self._files:
                img = cv2.imread(self._files[index], cv2.IMREAD_UNCHANGED)
                return _to_rgb8(img)
            if self._cap is None:
                return None
            if index != self._pos + 1:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, img = self._cap.read()
            self._pos = index if ok else -1
            return _to_rgb8(img) if ok else None

    def close(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def _to_rgb8(img):
    if img is None:
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        img = img[:, :, :3]
    if img.dtype in (np.float32, np.float64, np.float16):
        img = np.clip(img.astype(np.float32), 0, 1) ** (1 / 2.2) * 255
    elif img.dtype == np.uint16:
        img = img / 257.0
    return cv2.cvtColor(img.astype(np.uint8), cv2.COLOR_BGR2RGB)


class PreviewPanel(ttk.Frame):
    """Viewer with a frame scrubber, source picker and side-by-side compare."""

    def __init__(self, master, colors: dict):
        super().__init__(master)
        self.colors = colors
        self._sources: dict[str, FrameSource] = {}
        self._choices: dict[str, str] = {}
        self._photo = None
        self._render_job = None

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=4, pady=(4, 2))
        ttk.Label(bar, text="View:").pack(side="left")
        self.view_var = tk.StringVar(value="Input")
        self.view_box = ttk.Combobox(bar, textvariable=self.view_var, state="readonly", width=22)
        self.view_box.pack(side="left", padx=4)
        self.view_box.bind("<<ComboboxSelected>>", lambda e: self.render())
        self.compare_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Compare with input", variable=self.compare_var,
                        command=self.render).pack(side="left", padx=8)
        self.info_var = tk.StringVar(value="No clip selected")
        ttk.Label(bar, textvariable=self.info_var, style="Dim.TLabel").pack(side="right")

        self.canvas = tk.Canvas(self, highlightthickness=0, bg=colors["canvas"])
        self.canvas.pack(fill="both", expand=True, padx=4)
        self.canvas.bind("<Configure>", lambda e: self._schedule())

        nav = ttk.Frame(self)
        nav.pack(fill="x", padx=4, pady=(2, 4))
        ttk.Button(nav, text="⏮", width=3, command=lambda: self.step(-10**9)).pack(side="left")
        ttk.Button(nav, text="◀", width=3, command=lambda: self.step(-1)).pack(side="left")
        ttk.Button(nav, text="▶", width=3, command=lambda: self.step(1)).pack(side="left")
        ttk.Button(nav, text="⏭", width=3, command=lambda: self.step(10**9)).pack(side="left")
        self.frame_var = tk.DoubleVar(value=0)
        self.scale = ttk.Scale(nav, from_=0, to=0, variable=self.frame_var,
                               command=lambda v: self._schedule())
        self.scale.pack(side="left", fill="x", expand=True, padx=6)
        self.frame_label = ttk.Label(nav, text="0 / 0", width=12, anchor="e")
        self.frame_label.pack(side="left")

    # -- public API ---------------------------------------------------------

    def set_clip(self, input_path: str | None, outputs: dict[str, str] | None = None):
        outputs = outputs or {}
        choices = {}
        if input_path:
            choices["Input"] = input_path
        for label, path in outputs.items():
            choices[label] = path
        previous = self.view_var.get()
        self._choices = choices
        self.view_box["values"] = list(choices)
        if previous not in choices:
            self.view_var.set("Input" if "Input" in choices else next(iter(choices), ""))
        src = self._source("Input")
        if src is not None and src.ok:
            self.scale.configure(to=max(0, src.frame_count - 1))
            self.info_var.set(src.info())
        else:
            self.scale.configure(to=0)
            self.info_var.set("No clip selected" if not input_path else "Cannot read input")
        if self.frame_var.get() > float(self.scale.cget("to")):
            self.frame_var.set(0)
        self.render()

    def step(self, delta: int):
        top = float(self.scale.cget("to"))
        self.frame_var.set(max(0, min(top, round(self.frame_var.get()) + delta)))
        self.render()

    def current_frame(self) -> int:
        return int(round(self.frame_var.get()))

    def close(self):
        for src in self._sources.values():
            src.close()
        self._sources.clear()

    # -- rendering ----------------------------------------------------------

    def _source(self, label):
        path = self._choices.get(label)
        if not path:
            return None
        src = self._sources.get(path)
        if src is None:
            if len(self._sources) > 12:
                self.close()
            src = FrameSource(path)
            self._sources[path] = src
        return src

    def _schedule(self):
        if self._render_job is not None:
            self.after_cancel(self._render_job)
        self._render_job = self.after(30, self.render)

    def render(self):
        self._render_job = None
        self.canvas.delete("all")
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        idx = self.current_frame()
        top = int(float(self.scale.cget("to")))
        self.frame_label.configure(text=f"{idx} / {top}")
        label = self.view_var.get()
        main = self._source(label)
        if main is None or not main.ok:
            self.canvas.create_text(cw // 2, ch // 2, fill=self.colors["dim"],
                                    text="Select a clip in the queue to preview it\n"
                                         "or drop files here", justify="center")
            return
        frames = [main.read(idx)]
        if self.compare_var.get() and label != "Input":
            ref = self._source("Input")
            frames.insert(0, ref.read(idx) if ref else None)
        frames = [f for f in frames if f is not None]
        if not frames:
            return
        h = max(f.shape[0] for f in frames)
        frames = [cv2.resize(f, (int(f.shape[1] * h / f.shape[0]), h)) if f.shape[0] != h else f
                  for f in frames]
        if len(frames) > 1:
            gap = np.full((h, 6, 3), 40, np.uint8)
            img = np.hstack([frames[0], gap, frames[1]])
        else:
            img = frames[0]
        scale = min(cw / img.shape[1], ch / img.shape[0])
        size = (max(1, int(img.shape[1] * scale)), max(1, int(img.shape[0] * scale)))
        pil = Image.fromarray(img).resize(size, Image.BILINEAR if scale < 1 else Image.NEAREST)
        self._photo = ImageTk.PhotoImage(pil)
        self.canvas.create_image(cw // 2, ch // 2, image=self._photo)

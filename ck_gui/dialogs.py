"""Preferences, chroma hint maker, about and shortcut dialogs."""
from __future__ import annotations

import tkinter as tk
from dataclasses import asdict, fields
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from .config import APP_NAME, APP_VERSION, REPO_ROOT, Preferences


class Dialog(tk.Toplevel):
    """Modal dialog base with OK / Cancel handling."""

    def __init__(self, master, title: str):
        super().__init__(master)
        self.withdraw()
        self.title(title)
        self.transient(master)
        self.configure(background=master.cget("background"))
        self.result = None
        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill="both", expand=True)
        self.buttons = ttk.Frame(self, padding=(12, 0, 12, 12))
        self.buttons.pack(fill="x")
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda e: self.cancel())

    def show(self):
        self.update_idletasks()
        m = self.master
        x = m.winfo_rootx() + (m.winfo_width() - self.winfo_reqwidth()) // 2
        y = m.winfo_rooty() + (m.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        self.grab_set()
        self.focus_set()
        self.wait_window()
        return self.result

    def cancel(self):
        self.grab_release()
        self.destroy()


class FormBuilder:
    """Grid rows of label + widget bound to tk variables."""

    def __init__(self, parent):
        self.parent = parent
        self.vars: dict[str, tk.Variable] = {}
        self.row = 0
        parent.columnconfigure(1, weight=1)

    def add(self, key, label, kind="str", value=None, values=(), tip="", width=34):
        p = self.parent
        if kind == "bool":
            var = tk.BooleanVar(value=bool(value))
            ttk.Checkbutton(p, text=label, variable=var).grid(
                row=self.row, column=0, columnspan=3, sticky="w", pady=3)
        else:
            ttk.Label(p, text=label).grid(row=self.row, column=0, sticky="w", padx=(0, 10), pady=3)
            var = (tk.IntVar if kind == "int" else tk.DoubleVar if kind == "float"
                   else tk.StringVar)(value=value)
            if kind in ("combo", "combo_edit"):
                w = ttk.Combobox(p, textvariable=var, values=list(values), width=width - 2,
                                 state="readonly" if kind == "combo" else "normal")
            elif kind in ("int", "float"):
                lo, hi, inc = values or (0, 10**9, 1)
                w = ttk.Spinbox(p, textvariable=var, from_=lo, to=hi, increment=inc, width=width - 2)
            else:
                w = ttk.Entry(p, textvariable=var, width=width)
            w.grid(row=self.row, column=1, sticky="ew", pady=3)
            if kind in ("file", "dir"):
                ttk.Button(p, text="…", width=3,
                           command=lambda v=var, k=kind: self._browse(v, k)).grid(
                    row=self.row, column=2, padx=(4, 0))
        if tip:
            self.row += 1
            ttk.Label(p, text=tip, style="Dim.TLabel", wraplength=420).grid(
                row=self.row, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.vars[key] = var
        self.row += 1
        return var

    def section(self, text):
        ttk.Label(self.parent, text=text, style="Title.TLabel").grid(
            row=self.row, column=0, columnspan=3, sticky="w", pady=(10, 2))
        self.row += 1

    def _browse(self, var, kind):
        current = var.get()
        initial = str(Path(current).parent if kind == "file" else current) if current else None
        path = (filedialog.askopenfilename(initialdir=initial, parent=self.parent)
                if kind == "file" else filedialog.askdirectory(initialdir=initial, parent=self.parent))
        if path:
            var.set(path)

    def values(self) -> dict:
        out = {}
        for key, var in self.vars.items():
            try:
                out[key] = var.get()
            except tk.TclError:
                raise ValueError(f"Invalid value for '{key}'")
        return out


OUTPUT_LOCATIONS = {"next_to_clip": "Next to each clip", "custom_root": "Inside a fixed folder"}


class PreferencesDialog(Dialog):
    def __init__(self, master, prefs: Preferences, on_apply):
        super().__init__(master, "Preferences")
        self.on_apply = on_apply
        self.minsize(560, 480)
        nb = ttk.Notebook(self.body)
        nb.pack(fill="both", expand=True)
        self.forms = []
        p = prefs

        def tab(name):
            frame = ttk.Frame(nb, padding=12)
            nb.add(frame, text=name)
            form = FormBuilder(frame)
            self.forms.append(form)
            return form

        f = tab("General")
        f.section("Runtime")
        f.add("python_exe", "Python interpreter", "file", p.python_exe,
              tip=f"Leave empty to use the repo venv. Currently: {p.resolved_python()}")
        f.add("infer_script", "infer.py location", "file", p.infer_script,
              tip=f"Leave empty for {REPO_ROOT / 'infer.py'}")
        f.add("temp_dir", "Feature cache folder", "dir", p.temp_dir,
              tip="Low-VRAM mode stores large temporary feature files here.")
        f.section("Output")
        self._loc = f.add("output_location", "Output location", "combo",
                          OUTPUT_LOCATIONS.get(p.output_location), values=OUTPUT_LOCATIONS.values())
        f.add("output_root", "Fixed output folder", "dir", p.output_root)
        f.add("output_pattern", "Folder name pattern", "str", p.output_pattern,
              tip="{name} is replaced with the clip name, e.g. out_{name} or {name}_key.")
        f.add("skip_existing", "Skip clips whose outputs already exist", "bool", p.skip_existing)
        f.section("Behaviour")
        f.add("auto_detect_hints", "Auto-detect companion hint files when adding clips", "bool",
              p.auto_detect_hints)
        f.add("restore_queue", "Restore the queue on startup", "bool", p.restore_queue)
        f.add("open_output_when_done", "Open the output folder when a clip finishes", "bool",
              p.open_output_when_done)
        f.add("sound_on_finish", "Play a sound when the queue finishes", "bool", p.sound_on_finish)
        f.add("confirm_exit_while_running", "Ask before quitting while rendering", "bool",
              p.confirm_exit_while_running)

        f = tab("Encoding")
        f.section("Video outputs (ffmpeg)")
        f.add("ffmpeg_bin", "ffmpeg executable", "file", p.ffmpeg_bin)
        f.add("ffmpeg_codec", "Codec", "combo_edit", p.ffmpeg_codec,
              values=("libx264", "libx265", "h264_nvenc", "hevc_nvenc"),
              tip="Applies to alpha / fg / checker. Cutout is always ProRes 4444 with alpha.")
        f.add("crf", "CRF (quality, lower is better)", "int", p.crf, values=(0, 51, 1))
        f.add("preset", "Preset", "combo_edit", p.preset,
              values=("ultrafast", "superfast", "veryfast", "faster", "fast", "medium",
                      "slow", "slower", "veryslow"))
        f.add("pix_fmt", "Pixel format", "combo_edit", p.pix_fmt,
              values=("yuv444p10le", "yuv444p", "yuv420p10le", "yuv420p"),
              tip="yuv444p10le is 10-bit. Use yuv420p for maximum player compatibility.")
        f.add("bitrate", "Bitrate (optional, e.g. 50M)", "str", p.bitrate)
        f.add("ffmpeg_threads", "ffmpeg threads per output", "int", p.ffmpeg_threads, values=(0, 64, 1))
        f.section("EXR outputs")
        f.add("exr_dtype", "EXR pixel type", "combo", p.exr_dtype, values=("half", "float"))

        f = tab("Performance")
        f.add("stage2_batch", "Stage 2 batch size", "int", p.stage2_batch, values=(1, 16, 1),
              tip="Frames rendered together in stage 2. 1 uses least memory and is rarely slower.")
        f.section("Low-VRAM tuning (manual memory mode only)")
        f.add("low_vram_foundation_chunk", "Foundation precompute chunk", "int",
              p.low_vram_foundation_chunk, values=(1, 64, 1))
        f.add("low_vram_mlp_chunk_tokens", "MLP chunk tokens", "int",
              p.low_vram_mlp_chunk_tokens, values=(1024, 10**7, 1024))
        f.add("low_vram_enc_frame_chunk", "Encoder frame chunk", "int",
              p.low_vram_enc_frame_chunk, values=(1, 64, 1))
        f.add("low_vram_swin_window_batch", "Swin window batch", "int",
              p.low_vram_swin_window_batch, values=(1, 256, 1))
        f.add("low_vram_full_attn_query_chunk_tokens", "Full-attention query chunk", "int",
              p.low_vram_full_attn_query_chunk_tokens, values=(128, 10**6, 128))
        f.section("Monitoring")
        f.add("gpu_poll_seconds", "GPU status refresh (seconds)", "int", p.gpu_poll_seconds,
              values=(1, 60, 1))

        f = tab("Appearance")
        f.add("theme", "Theme", "combo", p.theme, values=("dark", "light"),
              tip="Menus pick up a new theme after a restart.")
        f.add("log_font_size", "Log font size", "int", p.log_font_size, values=(7, 20, 1))
        f.add("max_log_lines", "Log history (lines)", "int", p.max_log_lines, values=(500, 10**6, 500))

        ttk.Button(self.buttons, text="Restore Defaults", command=self.restore).pack(side="left")
        ttk.Button(self.buttons, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(self.buttons, text="Apply", command=self.apply).pack(side="right", padx=6)
        ttk.Button(self.buttons, text="OK", style="Accent.TButton", command=self.ok).pack(side="right")

    def _collect(self) -> Preferences:
        values = {}
        for form in self.forms:
            values.update(form.values())
        inverse = {v: k for k, v in OUTPUT_LOCATIONS.items()}
        values["output_location"] = inverse.get(values["output_location"], "next_to_clip")
        if "{name}" not in values["output_pattern"]:
            values["output_pattern"] += "_{name}"
        return Preferences(**values)

    def apply(self) -> bool:
        try:
            prefs = self._collect()
        except ValueError as exc:
            messagebox.showerror("Preferences", str(exc), parent=self)
            return False
        self.on_apply(prefs)
        return True

    def ok(self):
        if self.apply():
            self.result = True
            self.cancel()

    def restore(self):
        defaults = asdict(Preferences())
        for form in self.forms:
            for key, var in form.vars.items():
                value = defaults[key]
                if key == "output_location":
                    value = OUTPUT_LOCATIONS[value]
                var.set(value)


class HintMakerDialog(Dialog):
    """Build a first-frame hint matte from a quick chroma key."""

    def __init__(self, master, frame_rgb: np.ndarray, default_path: str, note: str = ""):
        super().__init__(master, "Make First-Frame Hint")
        self.frame = frame_rgb.astype(np.float32) / 255.0
        self.default_path = default_path
        self.matte = None
        self._photo = None

        left = ttk.Frame(self.body)
        left.pack(side="left", fill="y", padx=(0, 12))
        self.canvas = tk.Canvas(self.body, width=720, height=405, highlightthickness=0,
                                bg="#151719")
        self.canvas.pack(side="left", fill="both", expand=True)

        form = FormBuilder(left)
        self.key = form.add("key", "Screen colour", "combo", "Green", values=("Green", "Blue"), width=12)
        self.thr = self._slider(left, form, "Threshold", 0.0, 0.5, 0.08)
        self.soft = self._slider(left, form, "Softness", 0.01, 0.5, 0.12)
        self.grow = self._slider(left, form, "Shrink / grow (px)", -15, 15, 0, integer=True)
        self.clean = self._slider(left, form, "Clean-up (px)", 0, 25, 3, integer=True)
        self.invert = form.add("invert", "Invert matte", "bool", False)
        self.view = form.add("view", "Display", "combo", "Overlay", values=("Overlay", "Matte"), width=12)
        if note:
            ttk.Label(left, text=note, style="Dim.TLabel", wraplength=230).grid(
                row=form.row, column=0, columnspan=3, sticky="w", pady=(8, 0))
        for var in (self.key, self.invert, self.view):
            var.trace_add("write", lambda *a: self.update_preview())
        self.canvas.bind("<Configure>", lambda e: self.update_preview())

        ttk.Button(self.buttons, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(self.buttons, text="Save Hint…", style="Accent.TButton",
                   command=self.save).pack(side="right", padx=6)
        ttk.Label(self.buttons, text="White = subject, black = background",
                  style="Dim.TLabel").pack(side="left")
        self.update_preview()

    def _slider(self, parent, form, label, lo, hi, value, integer=False):
        ttk.Label(parent, text=label).grid(row=form.row, column=0, sticky="w", pady=(6, 0))
        var = tk.DoubleVar(value=value)
        readout = ttk.Label(parent, width=6, anchor="e")
        readout.grid(row=form.row, column=1, sticky="e")
        form.row += 1

        def changed(*_):
            v = var.get()
            readout.configure(text=f"{int(round(v))}" if integer else f"{v:.2f}")
            self.update_preview()

        ttk.Scale(parent, from_=lo, to=hi, variable=var, command=lambda _v: changed()).grid(
            row=form.row, column=0, columnspan=2, sticky="ew")
        form.row += 1
        readout.configure(text=f"{int(value)}" if integer else f"{value:.2f}")
        return var

    def compute(self) -> np.ndarray:
        r, g, b = self.frame[..., 0], self.frame[..., 1], self.frame[..., 2]
        dom = g - np.maximum(r, b) if self.key.get() == "Green" else b - np.maximum(r, g)
        soft = max(1e-3, self.soft.get())
        alpha = 1.0 - np.clip((dom - self.thr.get()) / soft, 0.0, 1.0)
        clean = int(round(self.clean.get()))
        if clean > 0:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (clean * 2 + 1,) * 2)
            alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, k)
            alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, k)
        grow = int(round(self.grow.get()))
        if grow:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (abs(grow) * 2 + 1,) * 2)
            alpha = cv2.dilate(alpha, k) if grow > 0 else cv2.erode(alpha, k)
        if self.invert.get():
            alpha = 1.0 - alpha
        return np.clip(alpha, 0.0, 1.0)

    def update_preview(self):
        if not self.winfo_exists():
            return
        self.matte = self.compute()
        if self.view.get() == "Matte":
            img = np.repeat(self.matte[..., None], 3, axis=2)
        else:
            tint = np.array([1.0, 0.15, 0.15], np.float32)
            img = self.frame * (0.35 + 0.65 * self.matte[..., None]) + \
                (1 - self.matte[..., None]) * tint * 0.25
        img = (np.clip(img, 0, 1) * 255).astype(np.uint8)
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        scale = min(cw / img.shape[1], ch / img.shape[0])
        size = (max(1, int(img.shape[1] * scale)), max(1, int(img.shape[0] * scale)))
        self._photo = ImageTk.PhotoImage(Image.fromarray(img).resize(size, Image.BILINEAR))
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self._photo)

    def save(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="Save hint matte", defaultextension=".png",
            initialdir=str(Path(self.default_path).parent),
            initialfile=Path(self.default_path).name, filetypes=[("PNG image", "*.png")])
        if not path:
            return
        ok, buf = cv2.imencode(".png", (self.matte * 255).astype(np.uint8))
        if not ok:
            messagebox.showerror("Hint", "Could not encode the matte.", parent=self)
            return
        Path(path).write_bytes(buf.tobytes())  # handles non-ASCII paths on Windows
        self.result = path
        self.cancel()


class TextDialog(Dialog):
    def __init__(self, master, title, text, width=70, height=24):
        super().__init__(master, title)
        box = tk.Text(self.body, width=width, height=height, wrap="word", relief="flat",
                      font=("Consolas", 10), padx=10, pady=8)
        style = ttk.Style(self)
        box.configure(background=style.lookup("TEntry", "fieldbackground") or "white",
                      foreground=style.lookup("TLabel", "foreground") or "black")
        scroll = ttk.Scrollbar(self.body, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        box.insert("1.0", text)
        box.configure(state="disabled")
        box.pack(fill="both", expand=True)
        ttk.Button(self.buttons, text="Close", command=self.cancel).pack(side="right")


SHORTCUTS = """\
Queue
  Ctrl+O            Add clips
  Ctrl+Shift+O      Add folder (batch / image sequence)
  Delete            Remove selected jobs
  Ctrl+D            Duplicate selected jobs
  Ctrl+Up / Down    Move selected jobs
  Ctrl+A            Select all jobs
  Space             Enable / disable selected jobs
  Double-click      Open output folder (finished) or preview

Run
  F5                Start queue
  Ctrl+F5           Run selected jobs only
  Shift+F5          Abort current render
  Ctrl+E            Open output folder
  Ctrl+Shift+C      Copy command line of selected job

Preview
  Left / Right      Previous / next frame (when the preview has focus)
  Home / End        First / last frame

Files
  Ctrl+S            Save queue
  Ctrl+L            Load queue
  Ctrl+,            Preferences
  F1                This list
  Ctrl+Q            Quit
"""


def about_text() -> str:
    return (f"{APP_NAME} {APP_VERSION}\n\n"
            "A desktop front end for the CorridorKey 2.0 neural keyer.\n\n"
            "CorridorKey 2.0 model by Zachary Harris with Niko and Corridor Digital.\n"
            "Foundation models: C-RADIO (NVIDIA), MoGe (Microsoft), RVM (Google DeepMind).\n\n"
            "Use of the model is governed by the CorridorKey license (Help > License).\n\n"
            "Project:          https://github.com/nikopueringer/CorridorKey2.0\n"
            "Official plugins: https://corridorkey.com")

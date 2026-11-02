"""Job settings inspector: edits the settings of every selected job."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from .jobs import ALL_OUTPUTS, JobSettings

HANN_PRESETS = {
    "80 / 40  max continuity": (80, 40),
    "48 / 24  high": (48, 24),
    "24 / 12  medium": (24, 12),
    "8 / 4  low": (8, 4),
    "4 / 2  very low": (4, 2),
    "1 / 1  per frame": (1, 1),
}


class Inspector(ttk.Frame):
    def __init__(self, master, on_change, on_make_hint):
        super().__init__(master)
        self.on_change = on_change
        self.on_make_hint = on_make_hint
        self._loading = False
        self.vars: dict[str, tk.Variable] = {}
        self._widgets: dict[str, list] = {}

        head = ttk.Frame(self)
        head.pack(fill="x", padx=8, pady=(6, 2))
        self.title_var = tk.StringVar(value="No job selected")
        ttk.Label(head, textvariable=self.title_var, style="Title.TLabel").pack(anchor="w")
        self.sub_var = tk.StringVar(value="Settings below are used for newly added clips.")
        ttk.Label(head, textvariable=self.sub_var, style="Dim.TLabel", wraplength=380).pack(anchor="w")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=4, pady=4)
        self._build_hint(self._tab("Hint"))
        self._build_output(self._tab("Output"))
        self._build_memory(self._tab("Memory"))
        self._build_range(self._tab("Range"))
        self._build_advanced(self._tab("Advanced"))

    # -- builders -----------------------------------------------------------

    def _tab(self, name):
        frame = ttk.Frame(self.nb, padding=10)
        frame.columnconfigure(1, weight=1)
        self.nb.add(frame, text=name)
        frame._row = 0
        return frame

    def _var(self, key, var):
        self.vars[key] = var
        var.trace_add("write", lambda *a, k=key: self._changed(k))
        return var

    def _track(self, group, *widgets):
        self._widgets.setdefault(group, []).extend(widgets)

    def _row(self, f, label, widget, group=None, button=None):
        ttk.Label(f, text=label).grid(row=f._row, column=0, sticky="w", padx=(0, 8), pady=3)
        widget.grid(row=f._row, column=1, sticky="ew", pady=3)
        if button is not None:
            button.grid(row=f._row, column=2, padx=(4, 0))
        if group:
            self._track(group, widget, *( [button] if button is not None else []))
        f._row += 1

    def _note(self, f, text):
        ttk.Label(f, text=text, style="Dim.TLabel", wraplength=360, justify="left").grid(
            row=f._row, column=0, columnspan=3, sticky="w", pady=(2, 6))
        f._row += 1

    def _spin(self, f, key, lo, hi, inc, kind=float, width=10):
        var = self._var(key, (tk.DoubleVar if kind is float else tk.IntVar)())
        return ttk.Spinbox(f, textvariable=var, from_=lo, to=hi, increment=inc, width=width)

    def _check(self, f, key, text, group=None):
        var = self._var(key, tk.BooleanVar())
        w = ttk.Checkbutton(f, text=text, variable=var)
        w.grid(row=f._row, column=0, columnspan=3, sticky="w", pady=3)
        if group:
            self._track(group, w)
        f._row += 1
        return w

    def _path(self, f, key, label, kind, group, filetypes=None):
        var = self._var(key, tk.StringVar())
        entry = ttk.Entry(f, textvariable=var)

        def browse():
            cur = var.get()
            init = str(Path(cur).parent) if cur else None
            if kind == "dir":
                p = filedialog.askdirectory(initialdir=init, parent=self)
            else:
                p = filedialog.askopenfilename(initialdir=init, parent=self,
                                               filetypes=filetypes or [("All files", "*.*")])
            if p:
                var.set(p)

        self._row(f, label, entry, group, ttk.Button(f, text="…", width=3, command=browse))

    def _build_hint(self, f):
        mode = self._var("hint_mode", tk.StringVar(value="none"))
        box = ttk.Frame(f)
        box.grid(row=f._row, column=0, columnspan=3, sticky="w", pady=(0, 6))
        for value, text in (("none", "No hint"), ("first_frame", "First-frame matte"),
                            ("video", "Hint video / sequence")):
            ttk.Radiobutton(box, text=text, value=value, variable=mode).pack(side="left", padx=(0, 10))
        f._row += 1
        self._path(f, "hint_first_frame", "First-frame matte", "file", "ff",
                   [("Images", "*.png *.jpg *.jpeg *.exr"), ("All files", "*.*")])
        make = ttk.Button(f, text="Make hint from chroma key…", command=self.on_make_hint)
        make.grid(row=f._row, column=1, sticky="w", pady=(0, 6))
        f._row += 1
        self._path(f, "hint_video", "Hint video", "file", "vid",
                   [("Video", "*.mp4 *.mov *.avi *.mkv *.webm"), ("All files", "*.*")])
        self._row(f, "Hint trust", self._spin(f, "hint_quality", 0, 1, 0.05), "hintq")
        self._note(f, "0.95 clean artist matte · 0.75 rough automated hint · 0.5 or less loose scribble.")
        self._check(f, "carry_hint", "Carry the model's own predictions forward (Hann carry)")
        self._row(f, "Carry trust", self._spin(f, "carry_hint_quality", 0, 1, 0.05), "carry")
        self._note(f, "Turn carry off to use a hint video literally on every frame.")

    def _build_output(self, f):
        ttk.Label(f, text="Outputs").grid(row=f._row, column=0, sticky="nw", pady=3)
        box = ttk.Frame(f)
        box.grid(row=f._row, column=1, columnspan=2, sticky="w")
        labels = {"alpha": "Alpha matte", "fg": "Foreground", "checker": "Checker preview",
                  "cutout": "Cutout (RGBA)"}
        for i, name in enumerate(ALL_OUTPUTS):
            var = self._var(f"out_{name}", tk.BooleanVar())
            ttk.Checkbutton(box, text=labels[name], variable=var).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 12))
        f._row += 1
        fmt = ttk.Combobox(f, textvariable=self._var("output_format", tk.StringVar()),
                           values=("video", "exr"), state="readonly", width=10)
        self._row(f, "Format", fmt)
        self._note(f, "video: ProRes/H.264 previews clipped to 0-1. exr: unclamped scene-linear "
                      "OpenEXR sequences for HDR compositing.")
        self._row(f, "Despill strength", self._spin(f, "despill_strength", 0, 1, 0.05), "despill")
        self._note(f, "Applies to checker and cutout. Use 0 when the subject contains green.")
        self._check(f, "cutout_linear", "Cutout in scene-linear colour (video format)", "despill")
        self._path(f, "output_dir", "Output folder", "dir", None)
        self.out_hint = tk.StringVar()
        ttk.Label(f, textvariable=self.out_hint, style="Dim.TLabel", wraplength=360).grid(
            row=f._row, column=0, columnspan=3, sticky="w")
        f._row += 1

    def _build_memory(self, f):
        mode = self._var("memory_mode", tk.StringVar(value="auto"))
        box = ttk.Frame(f)
        box.grid(row=f._row, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Radiobutton(box, text="Automatic (recommended)", value="auto", variable=mode).pack(side="left")
        ttk.Radiobutton(box, text="Manual", value="manual", variable=mode).pack(side="left", padx=12)
        f._row += 1
        self._note(f, "Automatic measures free GPU memory and picks the largest temporal window "
                      "that fits each clip.")
        self.preset_var = tk.StringVar()
        preset = ttk.Combobox(f, textvariable=self.preset_var, values=list(HANN_PRESETS),
                              state="readonly")
        preset.bind("<<ComboboxSelected>>", self._apply_preset)
        self._row(f, "Window preset", preset, "manual")
        self._row(f, "Hann chunk", self._spin(f, "hann_chunk", 1, 160, 1, int), "manual")
        self._row(f, "Hann stride", self._spin(f, "hann_stride", 1, 160, 1, int), "manual")
        self._check(f, "low_vram", "Low-VRAM staged inference (slower, uses disk cache)", "manual")
        self._note(f, "Larger windows give steadier mattes but need more VRAM. On an out-of-memory "
                      "error, enable Low-VRAM and pick a smaller window.")

    def _build_range(self, f):
        self._row(f, "Frames to process", self._spin(f, "num_frames", -1, 10**7, 1, int))
        self._note(f, "-1 processes the whole clip. Use a short range for quick look-dev tests.")
        sm = ttk.Combobox(f, textvariable=self._var("start_mode", tk.StringVar()),
                          values=("begin", "middle", "random_middle"), state="readonly", width=14)
        self._row(f, "Start at", sm, "range")
        self._row(f, "Random seed", self._spin(f, "seed", 0, 10**6, 1, int), "seed")
        ttk.Separator(f).grid(row=f._row, column=0, columnspan=3, sticky="ew", pady=8)
        f._row += 1
        ttk.Label(f, text="Image sequences", style="Title.TLabel").grid(
            row=f._row, column=0, columnspan=3, sticky="w")
        f._row += 1
        self._row(f, "Sequence fps", self._spin(f, "frame_dir_fps", 1, 240, 1), "seq")
        self._check(f, "frame_dir_linear", "Frames are scene-linear (e.g. linear EXR plates)", "seq")

    def _build_advanced(self, f):
        self._row(f, "Model scale", self._spin(f, "model_scale", 0.25, 2, 0.05))
        self._note(f, "Resample before inference. 1.0 = native resolution (recommended).")
        self._row(f, "Linear brightness", self._spin(f, "linear_brightness", 0.1, 4, 0.05))
        self._row(f, "Linear contrast", self._spin(f, "linear_contrast", 0.1, 4, 0.05))
        self._row(f, "Contrast pivot", self._spin(f, "linear_contrast_pivot", 0.01, 1, 0.01))
        self._note(f, "Experimental exposure adjustment applied before the model and inverted "
                      "on the foreground. Leave at 1.0 / 1.0 / 0.18 for normal work.")
        ttk.Button(f, text="Reset advanced values", command=self._reset_advanced).grid(
            row=f._row, column=0, columnspan=2, sticky="w", pady=6)
        f._row += 1

    # -- behaviour ----------------------------------------------------------

    def _apply_preset(self, _event=None):
        chunk, stride = HANN_PRESETS[self.preset_var.get()]
        self.vars["hann_chunk"].set(chunk)
        self.vars["hann_stride"].set(stride)

    def _reset_advanced(self):
        d = JobSettings()
        for key in ("model_scale", "linear_brightness", "linear_contrast", "linear_contrast_pivot"):
            self.vars[key].set(getattr(d, key))

    def _changed(self, key):
        self._update_states()
        if self._loading:
            return
        if key.startswith("out_"):
            value = [o for o in ALL_OUTPUTS if self.vars[f"out_{o}"].get()]
            key = "outputs"
        else:
            try:
                value = self.vars[key].get()
            except (tk.TclError, ValueError):
                return  # half-typed number
        self.on_change(key, value)

    def _set_state(self, group, enabled):
        for w in self._widgets.get(group, []):
            try:
                w.configure(state=("readonly" if isinstance(w, ttk.Combobox) else "normal")
                            if enabled else "disabled")
            except tk.TclError:
                pass

    def _update_states(self):
        get = lambda k: self.vars[k].get()
        try:
            mode = get("hint_mode")
            self._set_state("ff", mode == "first_frame")
            self._set_state("vid", mode == "video")
            self._set_state("hintq", mode != "none")
            self._set_state("carry", bool(get("carry_hint")))
            self._set_state("manual", get("memory_mode") == "manual")
            limited = int(get("num_frames")) > 0
            self._set_state("range", limited)
            self._set_state("seed", limited and get("start_mode") == "random_middle")
            self._set_state("despill", get("out_checker") or get("out_cutout"))
        except (tk.TclError, ValueError):
            pass

    def load(self, settings: JobSettings, title: str, subtitle: str, is_sequence: bool | None,
             output_hint: str = ""):
        self._loading = True
        try:
            for key, var in self.vars.items():
                if key.startswith("out_"):
                    var.set(key[4:] in settings.outputs)
                else:
                    var.set(getattr(settings, key))
            pair = (int(settings.hann_chunk), int(settings.hann_stride))
            self.preset_var.set(next((k for k, v in HANN_PRESETS.items() if v == pair), ""))
        finally:
            self._loading = False
        self.title_var.set(title)
        self.sub_var.set(subtitle)
        self.out_hint.set(output_hint)
        self._update_states()
        self._set_state("seq", is_sequence is not False)

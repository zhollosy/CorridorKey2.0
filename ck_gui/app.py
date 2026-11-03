"""CorridorKey Studio main window."""
from __future__ import annotations

import os
import queue
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # drag and drop is optional
    TkinterDnD = None

from . import dialogs
from .config import (APP_NAME, APP_VERSION, CONFIG_DIR, LAST_QUEUE_FILE, REPO_ROOT, Config,
                     Preferences)
from .inspector import Inspector
from .jobs import (Job, JobSettings, build_command, command_line, discover,
                   find_outputs, load_queue, mode_label, output_dir_for, save_queue)
from .preview import FrameSource, PreviewPanel
from .runner import ENV_CHECK_SCRIPT, GpuMonitor, QueueRunner, ToolRunner
from .theme import apply_theme

STATUS_ICONS = {"Queued": "•", "Running": "▶", "Done": "✓", "Failed": "✗",
                "Cancelled": "■", "Skipped": "↷"}
VIDEO_TYPES = [("Video clips", "*.mp4 *.mov *.avi *.mkv *.webm *.mxf *.m4v"), ("All files", "*.*")]
PROJECT_URL = "https://github.com/nikopueringer/CorridorKey2.0"


def fmt_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def open_path(path: str) -> None:
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - opening user files with their default app
    else:
        import subprocess
        subprocess.Popen(["xdg-open", path])


class App:
    def __init__(self, initial_paths=()):
        self.cfg = Config().load()
        self.root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
        self.root.title(APP_NAME)
        self.root.minsize(1100, 680)
        self.colors = apply_theme(self.root, self.cfg.prefs.theme)
        self._set_icon()

        self.jobs: list[Job] = []
        self.defaults = JobSettings.from_dict(self.cfg.state.defaults)
        self.events: queue.Queue = queue.Queue()
        self.runner = QueueRunner(self.events)
        self.tool = ToolRunner(self.events)
        self.gpu = GpuMonitor(self.events, self.cfg.prefs.gpu_poll_seconds)
        self._run_scope: set | None = None
        self._attempted: set = set()
        self._run_started = 0.0
        self._running_job: Job | None = None
        self._log_lines = 0
        self._run_total = self._run_done = 0
        self._job_t0 = 0.0

        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self._bind_keys()
        self._enable_dnd()

        self.root.geometry(self.cfg.state.geometry)
        if self.cfg.state.zoomed:
            self.root.state("zoomed")
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        if self.cfg.prefs.restore_queue and LAST_QUEUE_FILE.is_file():
            try:
                self._add_jobs(load_queue(LAST_QUEUE_FILE), select=False)
            except (OSError, ValueError, KeyError) as exc:
                self.log(f"Could not restore last queue: {exc}", "warn")
        if initial_paths:
            self.add_paths(initial_paths)
        self._on_select()
        self._apply_view_toggles()
        self.root.after(250, self._initial_sashes)
        self.gpu.start()
        self.log(f"{APP_NAME} {APP_VERSION} ready. Python: {self.cfg.prefs.resolved_python()}", "header")
        if TkinterDnD is None:
            self.log("Drag and drop is off: install 'tkinterdnd2' into the venv to enable it.", "warn")
        self.root.after(50, self._poll_events)
        self.root.after(1000, self._tick)

    # ======================================================================
    # Layout
    # ======================================================================

    def _set_icon(self):
        try:
            img = tk.PhotoImage(width=32, height=32)
            img.put(self.colors["accent"], to=(4, 4, 28, 28))
            img.put(self.colors["bg"], to=(10, 10, 22, 22))
            self.root.iconphoto(True, img)
            self._icon = img
        except tk.TclError:
            pass

    def _build_menu(self):
        m = tk.Menu(self.root)
        self.root.configure(menu=m)

        f = tk.Menu(m, tearoff=False)
        f.add_command(label="Add Clips…", accelerator="Ctrl+O", command=self.add_clips)
        f.add_command(label="Add Folder…", accelerator="Ctrl+Shift+O", command=self.add_folder)
        f.add_separator()
        f.add_command(label="Load Queue…", accelerator="Ctrl+L", command=self.load_queue_dialog)
        f.add_command(label="Save Queue As…", accelerator="Ctrl+S", command=self.save_queue_dialog)
        self.recent_menu = tk.Menu(f, tearoff=False, postcommand=self._fill_recent)
        f.add_cascade(label="Recent Queues", menu=self.recent_menu)
        f.add_separator()
        f.add_command(label="Preferences…", accelerator="Ctrl+,", command=self.preferences)
        f.add_separator()
        f.add_command(label="Exit", accelerator="Ctrl+Q", command=self.quit)
        m.add_cascade(label="File", menu=f)

        e = tk.Menu(m, tearoff=False)
        e.add_command(label="Select All", accelerator="Ctrl+A", command=self.select_all)
        e.add_command(label="Duplicate", accelerator="Ctrl+D", command=self.duplicate)
        e.add_command(label="Enable / Disable", accelerator="Space", command=self.toggle_enabled)
        e.add_command(label="Move Up", accelerator="Ctrl+Up", command=lambda: self.move(-1))
        e.add_command(label="Move Down", accelerator="Ctrl+Down", command=lambda: self.move(1))
        e.add_separator()
        e.add_command(label="Reset Status to Queued", command=self.reset_status)
        e.add_command(label="Remove", accelerator="Del", command=self.remove_selected)
        e.add_command(label="Remove Finished", command=self.clear_finished)
        e.add_command(label="Clear Queue", command=self.clear_all)
        e.add_separator()
        e.add_command(label="Apply Selected Settings to All Jobs", command=self.apply_to_all)
        e.add_command(label="Use Selected Settings as Default", command=self.save_as_default)
        e.add_command(label="Reset Defaults", command=self.reset_defaults)
        m.add_cascade(label="Edit", menu=e)

        r = tk.Menu(m, tearoff=False)
        r.add_command(label="Start Queue", accelerator="F5", command=self.start_queue)
        r.add_command(label="Run Selected", accelerator="Ctrl+F5", command=self.run_selected)
        r.add_command(label="Stop After Current", command=self.stop_after_current)
        r.add_command(label="Abort", accelerator="Shift+F5", command=self.abort)
        r.add_separator()
        r.add_command(label="Open Output Folder", accelerator="Ctrl+E", command=self.open_output)
        r.add_command(label="Play Alpha", command=lambda: self.play_output("alpha"))
        r.add_command(label="Play Checker", command=lambda: self.play_output("checker"))
        r.add_command(label="Copy Command Line", accelerator="Ctrl+Shift+C", command=self.copy_command)
        m.add_cascade(label="Render", menu=r)

        t = tk.Menu(m, tearoff=False)
        t.add_command(label="Make First-Frame Hint (Chroma Key)…", command=self.make_hint)
        t.add_separator()
        t.add_command(label="Check Environment", command=self.check_environment)
        t.add_command(label="Run Model Smoke Test", command=self.smoke_test)
        t.add_command(label="Download / Repair Weights", command=self.download_weights)
        t.add_command(label="Stop Running Tool", command=self.tool.abort)
        t.add_separator()
        t.add_command(label="Open Feature Cache Folder", command=self.open_cache)
        t.add_command(label="Clear Feature Cache…", command=self.clear_cache)
        t.add_command(label="Open Settings Folder", command=lambda: self._open_dir(CONFIG_DIR))
        m.add_cascade(label="Tools", menu=t)

        v = tk.Menu(m, tearoff=False)
        self.show_log_var = tk.BooleanVar(value=self.cfg.state.show_log)
        self.show_preview_var = tk.BooleanVar(value=self.cfg.state.show_preview)
        v.add_checkbutton(label="Log Panel", variable=self.show_log_var, command=self._apply_view_toggles)
        v.add_checkbutton(label="Preview Panel", variable=self.show_preview_var,
                          command=self._apply_view_toggles)
        self.wrap_log_var = tk.BooleanVar(value=self.cfg.state.wrap_log)
        v.add_checkbutton(label="Wrap Long Log Lines", variable=self.wrap_log_var,
                          command=self._apply_log_wrap)
        v.add_separator()
        self.theme_var = tk.StringVar(value=self.cfg.prefs.theme)
        v.add_radiobutton(label="Dark Theme", value="dark", variable=self.theme_var,
                          command=self._switch_theme)
        v.add_radiobutton(label="Light Theme", value="light", variable=self.theme_var,
                          command=self._switch_theme)
        m.add_cascade(label="View", menu=v)

        h = tk.Menu(m, tearoff=False)
        h.add_command(label="Keyboard Shortcuts", accelerator="F1", command=self.show_shortcuts)
        h.add_command(label="User Guide", command=self.show_guide)
        h.add_command(label="CorridorKey on GitHub", command=lambda: webbrowser.open(PROJECT_URL))
        h.add_command(label="corridorkey.com", command=lambda: webbrowser.open("https://corridorkey.com"))
        h.add_separator()
        h.add_command(label="License", command=self.show_license)
        h.add_command(label="About", command=self.about)
        m.add_cascade(label="Help", menu=h)

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(6, 6, 6, 2))
        bar.pack(fill="x")
        b = lambda text, cmd, style="Tool.TButton": ttk.Button(bar, text=text, command=cmd, style=style)
        b("＋ Clips", self.add_clips).pack(side="left")
        b("＋ Folder", self.add_folder).pack(side="left", padx=(4, 0))
        b("✕ Remove", self.remove_selected).pack(side="left", padx=(4, 0))
        b("▲", lambda: self.move(-1)).pack(side="left", padx=(12, 0))
        b("▼", lambda: self.move(1)).pack(side="left", padx=(2, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        self.start_btn = b("▶  Start Queue", self.start_queue, "Accent.TButton")
        self.start_btn.pack(side="left")
        self.stop_btn = b("⏸ Stop After Current", self.stop_after_current)
        self.stop_btn.pack(side="left", padx=(4, 0))
        self.abort_btn = b("■ Abort", self.abort)
        self.abort_btn.pack(side="left", padx=(4, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        b("📁 Output", self.open_output).pack(side="left")
        b("◐ Make Hint", self.make_hint).pack(side="left", padx=(4, 0))
        b("⚙ Preferences", self.preferences).pack(side="right")

    def _build_body(self):
        self.hpane = ttk.PanedWindow(self.root, orient="horizontal")
        self.hpane.pack(fill="both", expand=True, padx=6, pady=4)

        self.left = ttk.PanedWindow(self.hpane, orient="vertical")
        self.right = ttk.PanedWindow(self.hpane, orient="vertical")
        self.hpane.add(self.left, weight=3)
        self.hpane.add(self.right, weight=2)

        # Queue
        qf = ttk.Frame(self.left)
        cols = ("on", "name", "type", "mode", "outputs", "status", "progress", "time")
        self.tree = ttk.Treeview(qf, columns=cols, show="headings", selectmode="extended")
        heads = {"on": ("", 30), "name": ("Clip", 220), "type": ("Type", 74), "mode": ("Hint", 120),
                 "outputs": ("Outputs", 150), "status": ("Status", 100), "progress": ("Progress", 170),
                 "time": ("Time", 96)}
        for c, (text, width) in heads.items():
            self.tree.heading(c, text=text)
            self.tree.column(c, width=width, minwidth=30, stretch=c in ("name", "outputs", "status", "progress"),
                             anchor="center" if c in ("on", "type", "time") else "w")
        ysb = ttk.Scrollbar(qf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        c = self.colors
        for status, color in (("Done", c["ok"]), ("Failed", c["error"]), ("Running", c["accent"]),
                              ("Cancelled", c["warn"]), ("Skipped", c["dim"])):
            self.tree.tag_configure(status, foreground=color)
        self.tree.tag_configure("disabled", foreground=c["dim"])
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Button-3>", self._context_menu)
        self.tree.bind("<Button-1>", self._on_click, add=True)
        self.left.add(qf, weight=3)

        # Log
        lf = ttk.Frame(self.left)
        lbar = ttk.Frame(lf)
        lbar.pack(fill="x", pady=(2, 2))
        ttk.Label(lbar, text="Log", style="Title.TLabel").pack(side="left")
        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Button(lbar, text="Save…", command=self.save_log).pack(side="right")
        ttk.Button(lbar, text="Clear", command=self.clear_log).pack(side="right", padx=4)
        ttk.Checkbutton(lbar, text="Auto-scroll", variable=self.autoscroll).pack(side="right", padx=8)
        ttk.Checkbutton(lbar, text="Wrap lines", variable=self.wrap_log_var,
                        command=self._apply_log_wrap).pack(side="right", padx=8)
        body = ttk.Frame(lf)
        body.pack(fill="both", expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.logbox = tk.Text(body, height=10, wrap="none", relief="flat", padx=8, pady=6,
                              font=("Consolas", self.cfg.prefs.log_font_size),
                              background=c["canvas"], foreground=c["fg"], insertbackground=c["fg"],
                              selectbackground=c["select"])
        lsb = ttk.Scrollbar(body, orient="vertical", command=self.logbox.yview)
        self.log_hsb = ttk.Scrollbar(body, orient="horizontal", command=self.logbox.xview)
        self.logbox.configure(yscrollcommand=lsb.set, xscrollcommand=self.log_hsb.set,
                              state="disabled")
        self.logbox.grid(row=0, column=0, sticky="nsew")
        lsb.grid(row=0, column=1, sticky="ns")
        for tag in ("error", "warn", "cmd", "header", "ok", "dim"):
            self.logbox.tag_configure(tag, foreground=c[tag])
        self.logbox.tag_configure("header", font=("Consolas", self.cfg.prefs.log_font_size, "bold"))
        self._apply_log_wrap()
        self.log_frame = lf
        self.left.add(lf, weight=1)

        # Preview + inspector
        self.preview = PreviewPanel(self.right, self.colors)
        self.right.add(self.preview, weight=3)
        self.inspector = Inspector(self.right, self._on_setting_change, self.make_hint)
        self.right.add(self.inspector, weight=2)
        for key in ("<Left>", "<Right>", "<Home>", "<End>"):
            self.preview.canvas.bind(key, self._preview_key)
        self.preview.canvas.bind("<Button-1>", lambda e: self.preview.canvas.focus_set())

    def _build_statusbar(self):
        sb = ttk.Frame(self.root, style="Panel.TFrame")
        sb.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(sb, textvariable=self.status_var, style="Status.TLabel").pack(side="left")
        self.gpu_var = tk.StringVar(value="GPU: …")
        ttk.Label(sb, textvariable=self.gpu_var, style="Status.TLabel").pack(side="right")
        self.overall = ttk.Progressbar(sb, length=220, maximum=100)
        self.overall.pack(side="right", padx=8, pady=3)
        self.overall_var = tk.StringVar(value="")
        ttk.Label(sb, textvariable=self.overall_var, style="Status.TLabel").pack(side="right")
        self._update_buttons()

    def _bind_keys(self):
        r = self.root
        keys = {
            "<Control-o>": self.add_clips, "<Control-O>": self.add_folder,
            "<Control-s>": self.save_queue_dialog, "<Control-l>": self.load_queue_dialog,
            "<Control-comma>": self.preferences, "<Control-q>": self.quit,
            "<F5>": self.start_queue, "<Control-F5>": self.run_selected, "<Shift-F5>": self.abort,
            "<Control-e>": self.open_output, "<Control-C>": self.copy_command, "<F1>": self.show_shortcuts,
        }
        for seq, fn in keys.items():
            r.bind_all(seq, lambda e, f=fn: (f(), "break")[1])
        tree_keys = {
            "<Delete>": self.remove_selected, "<Control-a>": self.select_all,
            "<Control-d>": self.duplicate, "<space>": self.toggle_enabled,
            "<Control-Up>": lambda: self.move(-1), "<Control-Down>": lambda: self.move(1),
        }
        for seq, fn in tree_keys.items():
            self.tree.bind(seq, lambda e, f=fn: (f(), "break")[1])

    def _enable_dnd(self):
        if TkinterDnD is None:
            return
        for widget in (self.tree, self.preview.canvas):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event):
        self.add_paths(self.root.tk.splitlist(event.data))
        return event.action

    def _initial_sashes(self):
        """Start with a roomy preview and queue; panes otherwise open at their
        requested sizes, which lets the settings tabs crowd out the preview."""
        self.root.update_idletasks()
        try:
            if len(self.right.panes()) > 1:
                self.right.sashpos(0, int(self.right.winfo_height() * 0.55))
            if len(self.left.panes()) > 1:
                self.left.sashpos(0, int(self.left.winfo_height() * 0.62))
        except tk.TclError:
            pass

    def _apply_view_toggles(self):
        panes = [str(p) for p in self.left.panes()]
        if self.show_log_var.get() and str(self.log_frame) not in panes:
            self.left.add(self.log_frame, weight=1)
        elif not self.show_log_var.get() and str(self.log_frame) in panes:
            self.left.forget(self.log_frame)
        panes = [str(p) for p in self.right.panes()]
        if self.show_preview_var.get() and str(self.preview) not in panes:
            self.right.insert(0, self.preview, weight=3)
        elif not self.show_preview_var.get() and str(self.preview) in panes:
            self.right.forget(self.preview)
        self.cfg.state.show_log = self.show_log_var.get()
        self.cfg.state.show_preview = self.show_preview_var.get()

    def _switch_theme(self):
        self.cfg.prefs.theme = self.theme_var.get()
        self.cfg.save()
        self.colors = apply_theme(self.root, self.cfg.prefs.theme)
        c = self.colors
        self.logbox.configure(background=c["canvas"], foreground=c["fg"], selectbackground=c["select"])
        for tag in ("error", "warn", "cmd", "header", "ok", "dim"):
            self.logbox.tag_configure(tag, foreground=c[tag])
        self.preview.colors = c
        self.preview.canvas.configure(bg=c["canvas"])
        for status, color in (("Done", c["ok"]), ("Failed", c["error"]), ("Running", c["accent"]),
                              ("Cancelled", c["warn"]), ("Skipped", c["dim"])):
            self.tree.tag_configure(status, foreground=color)
        self.tree.tag_configure("disabled", foreground=c["dim"])
        self.preview.render()
        self.log("Theme changed. Menus update after a restart.", "ok")

    # ======================================================================
    # Queue management
    # ======================================================================

    def job(self, job_id) -> Job | None:
        return next((j for j in self.jobs if j.id == job_id), None)

    def selected(self) -> list[Job]:
        ids = self.tree.selection()
        return [j for j in self.jobs if j.id in ids]

    def _row_values(self, job: Job):
        s = job.settings
        outs = ", ".join(o for o in ("alpha", "fg", "checker", "cutout") if o in s.outputs)
        if s.output_format == "exr":
            outs += "  [EXR]"
        bar_len = 8
        filled = int(round(job.progress / 100 * bar_len))
        if job.status == "Running":
            prog = "█" * filled + "·" * (bar_len - filled) + f" {job.progress:.0f}%  {job.stage}"
        elif job.status == "Done":
            prog = "█" * bar_len + " 100%"
        else:
            prog = job.stage if job.status in ("Failed", "Cancelled", "Skipped") else ""
        if job.status == "Running" and job.elapsed:
            t = fmt_time(job.elapsed)
            if job.progress >= 25:
                t += f" / ~{fmt_time(job.elapsed / (job.progress / 100))}"
        else:
            t = fmt_time(job.elapsed) if job.elapsed else ""
        return ("☑" if job.enabled else "☐", job.name, job.kind, mode_label(job), outs,
                f"{STATUS_ICONS.get(job.status, '')} {job.status}", prog, t)

    def _refresh_row(self, job: Job):
        if self.tree.exists(job.id):
            tags = (job.status,) if job.enabled else ("disabled",)
            self.tree.item(job.id, values=self._row_values(job), tags=tags)

    def _rebuild_tree(self, keep_selection=True):
        sel = set(self.tree.selection()) if keep_selection else set()
        self.tree.delete(*self.tree.get_children())
        for job in self.jobs:
            self.tree.insert("", "end", iid=job.id, values=self._row_values(job))
            self._refresh_row(job)
        keep = [i for i in sel if self.tree.exists(i)]
        if keep:
            self.tree.selection_set(keep)
        self._update_status_text()

    def _add_jobs(self, jobs, select=True):
        added = list(jobs)
        self.jobs.extend(added)
        self._rebuild_tree()
        if select and added:
            self.tree.selection_set([j.id for j in added])
            self.tree.see(added[-1].id)
        return added

    def add_paths(self, paths):
        queued = {j.input_path for j in self.jobs if j.status == "Queued"}
        jobs = [j for j in discover(paths, self.defaults, self.cfg.prefs.auto_detect_hints)
                if j.input_path not in queued]
        if not jobs:
            self.log("Nothing to add: no new supported clips or frame sequences found.", "warn")
            return
        added = self._add_jobs(jobs)
        hinted = sum(1 for j in added if j.settings.hint_mode != "none")
        self.log(f"Added {len(added)} job(s)" + (f", {hinted} with auto-detected hints." if hinted else "."), "ok")
        if paths:
            self.cfg.state.last_dir = str(Path(paths[0]).parent)
        self._autosave_queue()

    def add_clips(self):
        files = filedialog.askopenfilenames(title="Add clips", filetypes=VIDEO_TYPES,
                                            initialdir=self.cfg.state.last_dir or None)
        if files:
            self.add_paths(files)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Add a folder of clips or an image sequence",
                                         initialdir=self.cfg.state.last_dir or None)
        if folder:
            self.add_paths([folder])

    def remove_selected(self):
        sel = [j for j in self.selected() if j.status != "Running"]
        if not sel:
            return
        ids = {j.id for j in sel}
        self.jobs = [j for j in self.jobs if j.id not in ids]
        self._rebuild_tree(keep_selection=False)
        self._on_select()
        self._autosave_queue()

    def clear_finished(self):
        self.jobs = [j for j in self.jobs if j.status not in ("Done", "Skipped")]
        self._rebuild_tree()
        self._on_select()
        self._autosave_queue()

    def clear_all(self):
        if self.runner.running:
            messagebox.showinfo(APP_NAME, "Stop the queue before clearing it.")
            return
        if self.jobs and messagebox.askyesno(APP_NAME, f"Remove all {len(self.jobs)} jobs?"):
            self.jobs.clear()
            self._rebuild_tree(keep_selection=False)
            self._on_select()
            self._autosave_queue()

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def duplicate(self):
        copies = []
        for j in self.selected():
            copies.append(Job(input_path=j.input_path, settings=j.settings.copy()))
        if copies:
            self.jobs.extend(copies)
            self._rebuild_tree(keep_selection=False)
            self.tree.selection_set([j.id for j in copies])
            self._autosave_queue()

    def toggle_enabled(self):
        sel = self.selected()
        if not sel:
            return
        state = not all(j.enabled for j in sel)
        for j in sel:
            j.enabled = state
            self._refresh_row(j)
        self._update_status_text()

    def move(self, delta):
        ids = set(self.tree.selection())
        if not ids:
            return
        order = list(self.jobs)
        rng = range(len(order)) if delta < 0 else range(len(order) - 1, -1, -1)
        for i in rng:
            j = i + delta
            if order[i].id in ids and 0 <= j < len(order) and order[j].id not in ids:
                order[i], order[j] = order[j], order[i]
        self.jobs = order
        self._rebuild_tree()
        self.tree.see(next(iter(ids)))

    def reset_status(self):
        for j in self.selected():
            if j.status != "Running":
                j.status, j.progress, j.stage, j.elapsed = "Queued", 0.0, "", 0.0
                self._refresh_row(j)
        self._update_status_text()

    def apply_to_all(self):
        sel = self.selected()
        if not sel:
            return
        src = sel[0].settings
        for j in self.jobs:
            if j is sel[0] or j.status == "Running":
                continue
            keep = (j.settings.hint_mode, j.settings.hint_first_frame, j.settings.hint_video,
                    j.settings.output_dir)
            j.settings = src.copy()
            (j.settings.hint_mode, j.settings.hint_first_frame, j.settings.hint_video,
             j.settings.output_dir) = keep
            self._refresh_row(j)
        self.log("Applied settings to all jobs (each job keeps its own hint files and output folder).", "ok")

    def save_as_default(self):
        sel = self.selected()
        if sel:
            self.defaults = sel[0].settings.copy()
            self.defaults.hint_mode, self.defaults.hint_first_frame = "none", ""
            self.defaults.hint_video, self.defaults.output_dir = "", ""
            self._save_defaults()
            self.log("Saved as default settings for new clips.", "ok")

    def reset_defaults(self):
        self.defaults = JobSettings()
        self._save_defaults()
        self._on_select()
        self.log("Default job settings reset.", "ok")

    def _save_defaults(self):
        self.cfg.state.defaults = self.defaults.to_dict()
        self.cfg.save()

    # -- selection / inspector ---------------------------------------------

    def _on_select(self):
        sel = self.selected()
        prefs = self.cfg.prefs
        if not sel:
            self.inspector.load(self.defaults, "Default settings",
                                "No job selected: changes apply to clips you add next.", None)
            self.preview.set_clip(None)
            return
        job = sel[0]
        if len(sel) == 1:
            sub = f"{job.input_path}"
            title = job.name
        else:
            title = f"{len(sel)} jobs selected"
            sub = "Changes apply to every selected job."
        out_hint = "" if job.settings.output_dir else f"Auto: {output_dir_for(job, prefs)}"
        self.inspector.load(job.settings, title, sub, job.kind == "Sequence", out_hint)
        self.preview.set_clip(job.input_path, find_outputs(job, prefs))

    def _on_setting_change(self, key, value):
        targets = self.selected()
        if not targets:
            setattr(self.defaults, key, value)
            self._save_defaults()
            return
        for j in targets:
            if j.status == "Running":
                continue
            setattr(j.settings, key, value)
            self._refresh_row(j)
        if key == "output_dir" and len(targets) == 1:
            j = targets[0]
            self.inspector.out_hint.set("" if value else f"Auto: {output_dir_for(j, self.cfg.prefs)}")

    def _on_click(self, event):
        if self.tree.identify_column(event.x) == "#1" and self.tree.identify_region(event.x, event.y) == "cell":
            row = self.tree.identify_row(event.y)
            job = self.job(row)
            if job:
                job.enabled = not job.enabled
                self._refresh_row(job)
                self._update_status_text()
                return "break"

    def _on_double(self, event):
        job = self.job(self.tree.identify_row(event.y))
        if job and job.status == "Done":
            self.open_output()

    def _context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Run Selected", command=self.run_selected)
        menu.add_command(label="Open Output Folder", command=self.open_output)
        menu.add_command(label="Play Alpha", command=lambda: self.play_output("alpha"))
        menu.add_command(label="Play Checker", command=lambda: self.play_output("checker"))
        menu.add_separator()
        menu.add_command(label="Make First-Frame Hint…", command=self.make_hint)
        menu.add_command(label="Copy Command Line", command=self.copy_command)
        menu.add_command(label="Reveal Input", command=self.reveal_input)
        menu.add_separator()
        menu.add_command(label="Enable / Disable", command=self.toggle_enabled)
        menu.add_command(label="Duplicate", command=self.duplicate)
        menu.add_command(label="Reset Status", command=self.reset_status)
        menu.add_command(label="Remove", command=self.remove_selected)
        menu.tk_popup(event.x_root, event.y_root)

    def _preview_key(self, event):
        steps = {"Left": -1, "Right": 1, "Home": -10**9, "End": 10**9}
        self.preview.step(steps[event.keysym])
        return "break"

    # ======================================================================
    # Rendering
    # ======================================================================

    def _next_job(self):
        """Called from the worker thread: pick and claim the next job."""
        for job in list(self.jobs):
            if job.id in self._attempted or not job.enabled or job.status != "Queued":
                continue
            if self._run_scope is not None and job.id not in self._run_scope:
                continue
            self._attempted.add(job.id)
            return job
        return None

    def _begin(self, scope):
        if self.runner.running:
            return
        if self.tool.running:
            messagebox.showinfo(APP_NAME, "Wait for the running tool to finish first.")
            return
        self._run_scope = scope
        self._attempted = set()
        pending = [j for j in self.jobs if j.enabled and j.status == "Queued"
                   and (scope is None or j.id in scope)]
        if not pending:
            if scope is None and self.jobs:
                messagebox.showinfo(APP_NAME, "No queued jobs. Use Edit > Reset Status to re-render "
                                              "finished jobs.")
            return
        self._run_total = len(pending)
        self._run_done = 0
        self._run_started = time.time()
        self.runner.start(self._next_job, self.cfg.prefs)
        self.log(f"Starting render of {len(pending)} job(s).", "header")
        self._update_buttons()

    def start_queue(self):
        self._begin(None)

    def run_selected(self):
        sel = [j for j in self.selected() if j.status != "Running"]
        if not sel:
            return
        for j in sel:
            if j.status != "Queued":
                j.status, j.progress, j.stage = "Queued", 0.0, ""
                self._refresh_row(j)
            j.enabled = True
        if self.runner.running:
            if self._run_scope is not None:
                self._run_scope.update(j.id for j in sel)
            self._run_total += len(sel)
            self.log(f"Added {len(sel)} job(s) to the running render.", "ok")
            return
        self._begin({j.id for j in sel})

    def stop_after_current(self):
        if self.runner.running:
            self.runner.stop_after_current()
            self.log("Will stop after the current clip.", "warn")
            self.status_var.set("Stopping after current clip…")

    def abort(self):
        if self.runner.running:
            self.runner.abort()
            self.log("Aborting render…", "warn")
        elif self.tool.running:
            self.tool.abort()

    def _update_buttons(self):
        running = self.runner.running
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
        self.abort_btn.configure(state="normal" if running or self.tool.running else "disabled")

    def _update_status_text(self):
        counts = {}
        for j in self.jobs:
            counts[j.status] = counts.get(j.status, 0) + 1
        if not self.jobs:
            self.status_var.set("Queue empty. Drop clips or folders here, or press Ctrl+O.")
            return
        parts = [f"{len(self.jobs)} jobs"] + [f"{n} {s.lower()}" for s, n in counts.items()]
        disabled = sum(1 for j in self.jobs if not j.enabled)
        if disabled:
            parts.append(f"{disabled} disabled")
        self.status_var.set("  ·  ".join(parts))

    # ======================================================================
    # Events from worker threads
    # ======================================================================

    def _poll_events(self):
        lines = []
        try:
            for _ in range(500):
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "log":
                    lines.append((ev[2], ev[3] if len(ev) > 3 else None))
                    continue
                if lines:
                    self._write_log(lines)
                    lines = []
                self._handle_event(ev)
        except queue.Empty:
            pass
        if lines:
            self._write_log(lines)
        self.root.after(50, self._poll_events)

    def _handle_event(self, ev):
        kind = ev[0]
        if kind == "progress":
            job = self.job(ev[1])
            if job:
                job.progress, job.stage, job.elapsed = ev[2], ev[3], ev[4]
                self._refresh_row(job)
                self._update_overall(job)
        elif kind == "status":
            _, job_id, status, progress, message, *rest = ev
            job = self.job(job_id)
            if not job:
                return
            job.status, job.progress, job.stage = status, progress, message
            if rest:
                job.output_dir_used = rest[0]
            if len(rest) > 1:
                job.elapsed = rest[1]
            if status == "Running":
                self._running_job = job
                job.elapsed = 0.0
                self._job_t0 = time.time()
            else:
                self._running_job = None
                self._run_done += 1
                tag = {"Done": "ok", "Failed": "error"}.get(status, "warn")
                self.log(f"{job.name}: {status}" + (f" - {message}" if message and status != "Done" else "")
                         + (f" in {fmt_time(job.elapsed)}" if job.elapsed else ""), tag)
                if status == "Done":
                    if self.cfg.prefs.open_output_when_done and job.output_dir_used:
                        self._open_dir(job.output_dir_used)
                    if job in self.selected():
                        self.preview.set_clip(job.input_path, find_outputs(job, self.cfg.prefs))
            self._refresh_row(job)
            self._update_status_text()
            self._update_overall(job)
        elif kind == "queue_done":
            summary, elapsed = ev[1], ev[2]
            text = ", ".join(f"{n} {s.lower()}" for s, n in summary.items() if n)
            self.log(f"Queue finished in {fmt_time(elapsed)}: {text or 'nothing rendered'}.", "header")
            self.overall.configure(value=0)
            self.overall_var.set("")
            self.root.title(APP_NAME)
            self._update_buttons()
            self._autosave_queue()
            if self.cfg.prefs.sound_on_finish:
                self._chime(summary.get("Failed", 0) == 0)
            if not self.root.focus_displayof():
                try:
                    self.root.attributes("-topmost", True)
                    self.root.after(300, lambda: self.root.attributes("-topmost", False))
                except tk.TclError:
                    pass
        elif kind == "tool_done":
            title, code = ev[1], ev[2]
            self.log(f"{title}: {'finished' if code == 0 else f'failed (exit code {code})'}",
                     "ok" if code == 0 else "error")
            self._update_buttons()
        elif kind == "gpu":
            info = ev[1]
            if info is None:
                self.gpu_var.set("GPU: unavailable")
            else:
                self.gpu_var.set(f"{info['name']}  ·  VRAM {info['used'] / 1024:.1f}/"
                                 f"{info['total'] / 1024:.1f} GB  ·  {info['util']}%  ·  {info['temp']}°C")

    def _update_overall(self, job):
        if not self.runner.running and job.status != "Running":
            return
        total = max(1, self._run_total)
        current = job.progress if job.status == "Running" else 0
        pct = min(100.0, (self._run_done * 100 + current) / total)
        self.overall.configure(value=pct)
        self.overall_var.set(f"Clip {min(self._run_done + 1, total)}/{total}  ·  {pct:.0f}%")
        self.root.title(f"[{pct:.0f}%] {APP_NAME}")

    def _tick(self):
        job = self._running_job
        if job is not None and job.status == "Running":
            job.elapsed = time.time() - self._job_t0
            self._refresh_row(job)
        self.root.after(1000, self._tick)

    def _chime(self, success):
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK if success else winsound.MB_ICONHAND)
        except (ImportError, RuntimeError):
            self.root.bell()

    # ======================================================================
    # Log
    # ======================================================================

    def log(self, text, tag=None):
        self._write_log([(text, tag)])

    def _write_log(self, lines):
        box = self.logbox
        box.configure(state="normal")
        for text, tag in lines:
            stamp = time.strftime("%H:%M:%S ")
            box.insert("end", stamp, ("dim", "line"))
            box.insert("end", text.lstrip("\n") + "\n", (tag, "line") if tag else ("line",))
            self._log_lines += 1
        overflow = self._log_lines - self.cfg.prefs.max_log_lines
        if overflow > 0:
            box.delete("1.0", f"{overflow + 1}.0")
            self._log_lines -= overflow
        box.configure(state="disabled")
        if self.autoscroll.get():
            box.see("end")

    def _apply_log_wrap(self):
        """Toggle word wrap; wrapped lines get a hanging indent past the timestamp."""
        wrap = self.wrap_log_var.get()
        self.logbox.configure(wrap="word" if wrap else "none")
        indent = tkfont.Font(font=self.logbox.cget("font")).measure("00:00:00 ")
        # Tk reads lmargin2 from the first character of each display line, so
        # every log character carries the shared "line" tag.
        self.logbox.tag_configure("line", lmargin2=indent)
        if wrap:
            self.log_hsb.grid_remove()
        else:
            self.log_hsb.grid(row=1, column=0, sticky="ew")
        self.cfg.state.wrap_log = wrap

    def clear_log(self):
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")
        self._log_lines = 0

    def save_log(self):
        path = filedialog.asksaveasfilename(title="Save log", defaultextension=".log",
                                            initialfile=time.strftime("corridorkey_%Y%m%d_%H%M%S.log"),
                                            filetypes=[("Log file", "*.log"), ("Text", "*.txt")])
        if path:
            Path(path).write_text(self.logbox.get("1.0", "end"), encoding="utf-8")

    # ======================================================================
    # Output helpers
    # ======================================================================

    def _first_selected(self, quiet=False):
        sel = self.selected()
        if not sel and not quiet:
            messagebox.showinfo(APP_NAME, "Select a job in the queue first.")
        return sel[0] if sel else None

    def _open_dir(self, path):
        path = Path(path)
        if not path.exists():
            messagebox.showinfo(APP_NAME, f"Folder does not exist yet:\n{path}")
            return
        open_path(str(path))

    def open_output(self):
        job = self._first_selected()
        if job:
            self._open_dir(job.output_dir_used or output_dir_for(job, self.cfg.prefs))

    def play_output(self, label):
        job = self._first_selected()
        if not job:
            return
        outs = find_outputs(job, self.cfg.prefs)
        match = next((p for k, p in outs.items() if k.startswith(label)), None)
        if match:
            open_path(match)
        else:
            messagebox.showinfo(APP_NAME, f"No '{label}' output found for {job.name}.")

    def reveal_input(self):
        job = self._first_selected()
        if job:
            if os.name == "nt":
                import subprocess
                subprocess.Popen(["explorer", "/select,", os.path.normpath(job.input_path)])
            else:
                open_path(str(Path(job.input_path).parent))

    def copy_command(self):
        job = self._first_selected()
        if job:
            cmd = command_line(build_command(job, self.cfg.prefs))
            self.root.clipboard_clear()
            self.root.clipboard_append(cmd)
            self.log("Copied command line to the clipboard:", "ok")
            self.log(cmd, "cmd")

    # ======================================================================
    # Tools
    # ======================================================================

    def make_hint(self):
        job = self._first_selected()
        if not job:
            return
        src = FrameSource(job.input_path)
        try:
            frame = src.read(0)
        finally:
            src.close()
        if frame is None:
            messagebox.showerror(APP_NAME, "Could not read the first frame of this clip.")
            return
        base = Path(job.input_path)
        if base.is_dir() and base.name.lower() == "input":
            base = base.parent
        default = base.parent / f"{base.stem if base.is_file() else base.name}FrameHint.png"
        note = ""
        if int(job.settings.num_frames) > 0 and job.settings.start_mode != "begin":
            note = ("Note: this job starts mid-clip, but the hint is built from frame 0. "
                    "Set Start at = begin for first-frame hints.")
        path = dialogs.HintMakerDialog(self.root, frame, str(default), note).show()
        if path:
            job.settings.hint_mode, job.settings.hint_first_frame = "first_frame", path
            self._refresh_row(job)
            self._on_select()
            self.log(f"Hint saved and assigned to {job.name}: {path}", "ok")

    def _run_tool(self, title, args):
        if self.runner.running:
            messagebox.showinfo(APP_NAME, "Tools cannot run while the queue is rendering.")
            return
        if not self.tool.start(title, [self.cfg.prefs.resolved_python(), *args], str(REPO_ROOT)):
            messagebox.showinfo(APP_NAME, "Another tool is still running.")
        self._update_buttons()

    def check_environment(self):
        self._run_tool("Environment check", ["-c", ENV_CHECK_SCRIPT, self.cfg.prefs.ffmpeg_bin])

    def smoke_test(self):
        self._run_tool("Model smoke test", ["-u", str(REPO_ROOT / "scripts" / "smoke_test_runtime.py"),
                                            "--load_model"])

    def download_weights(self):
        if messagebox.askyesno(APP_NAME, "Download any missing model weights (about 5 GB on first "
                                         "run) from Hugging Face and the original publishers?"):
            self._run_tool("Download weights", ["-u", str(REPO_ROOT / "scripts" / "download_weights.py")])

    def open_cache(self):
        path = Path(self.cfg.prefs.temp_dir)
        path.mkdir(parents=True, exist_ok=True)
        open_path(str(path))

    def clear_cache(self):
        if self.runner.running:
            messagebox.showinfo(APP_NAME, "Cannot clear the cache while rendering.")
            return
        path = Path(self.cfg.prefs.temp_dir)
        files = [p for p in path.glob("*") if p.is_file()] if path.is_dir() else []
        size = sum(p.stat().st_size for p in files)
        if not files:
            messagebox.showinfo(APP_NAME, "The feature cache is already empty.")
            return
        if messagebox.askyesno(APP_NAME, f"Delete {len(files)} cached feature files "
                                         f"({size / 1e9:.2f} GB) from\n{path}?"):
            for p in files:
                try:
                    p.unlink()
                except OSError as exc:
                    self.log(f"Could not delete {p.name}: {exc}", "warn")
            self.log(f"Cleared feature cache ({size / 1e9:.2f} GB).", "ok")

    # ======================================================================
    # Files, preferences, dialogs
    # ======================================================================

    def _autosave_queue(self):
        try:
            save_queue(LAST_QUEUE_FILE, self.jobs)
        except OSError:
            pass

    def save_queue_dialog(self):
        path = filedialog.asksaveasfilename(title="Save queue", defaultextension=".ckqueue",
                                            filetypes=[("CorridorKey queue", "*.ckqueue"),
                                                       ("JSON", "*.json")])
        if path:
            save_queue(path, self.jobs)
            self.cfg.add_recent(path)
            self.log(f"Queue saved to {path}", "ok")

    def load_queue_dialog(self, path=None):
        path = path or filedialog.askopenfilename(title="Load queue", filetypes=[
            ("CorridorKey queue", "*.ckqueue"), ("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            jobs = load_queue(path)
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror(APP_NAME, f"Could not load queue:\n{exc}")
            return
        if self.jobs and not self.runner.running and messagebox.askyesno(
                APP_NAME, "Replace the current queue? Choose No to append."):
            self.jobs.clear()
        self._add_jobs(jobs)
        self.cfg.add_recent(path)
        self.log(f"Loaded {len(jobs)} job(s) from {path}", "ok")

    def _fill_recent(self):
        self.recent_menu.delete(0, "end")
        recent = [p for p in self.cfg.state.recent_queues if Path(p).is_file()]
        if not recent:
            self.recent_menu.add_command(label="(empty)", state="disabled")
        for p in recent:
            self.recent_menu.add_command(label=p, command=lambda p=p: self.load_queue_dialog(p))

    def preferences(self):
        dialogs.PreferencesDialog(self.root, self.cfg.prefs, self._apply_prefs).show()

    def _apply_prefs(self, prefs: Preferences):
        old = self.cfg.prefs
        self.cfg.prefs = prefs
        self.cfg.save()
        self.logbox.configure(font=("Consolas", prefs.log_font_size))
        self.logbox.tag_configure("header", font=("Consolas", prefs.log_font_size, "bold"))
        self._apply_log_wrap()
        if prefs.theme != old.theme:
            self.theme_var.set(prefs.theme)
            self._switch_theme()
        if prefs.gpu_poll_seconds != old.gpu_poll_seconds:
            self.gpu.interval = max(1.0, float(prefs.gpu_poll_seconds))
        self._on_select()
        self.log("Preferences saved.", "ok")

    def show_shortcuts(self):
        dialogs.TextDialog(self.root, "Keyboard Shortcuts", dialogs.SHORTCUTS, 60, 30).show()

    def _show_text_file(self, title, path, width=90, height=32):
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            text = f"{Path(path).name} is missing from this installation.\n\nSee {PROJECT_URL}"
        dialogs.TextDialog(self.root, title, text, width, height).show()

    def show_license(self):
        self._show_text_file("CorridorKey License", REPO_ROOT / "LICENSE")

    def show_guide(self):
        self._show_text_file("CorridorKey Studio Guide", REPO_ROOT / "docs" / "CorridorKey_Studio.md")

    def about(self):
        dialogs.TextDialog(self.root, f"About {APP_NAME}", dialogs.about_text(), 78, 16).show()

    def quit(self):
        if self.runner.running and self.cfg.prefs.confirm_exit_while_running:
            if not messagebox.askyesno(APP_NAME, "A render is running. Abort it and quit?"):
                return
        self.runner.abort()
        self.tool.abort()
        self.gpu.stop()
        zoomed = self.root.state() == "zoomed"
        self.cfg.state.zoomed = zoomed
        if not zoomed:
            self.cfg.state.geometry = self.root.geometry()
        self.cfg.state.defaults = self.defaults.to_dict()
        self._autosave_queue()
        try:
            self.cfg.save()
        except OSError:
            pass
        self.preview.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    App([a for a in argv if os.path.exists(a)]).run()

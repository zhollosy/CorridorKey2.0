"""ttk styling for the dark and light themes."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

PALETTES = {
    "dark": {
        "bg": "#1f2124", "panel": "#26292d", "field": "#2f3337", "fg": "#e3e5e8",
        "dim": "#8b9096", "accent": "#3ddc84", "accent_fg": "#0d1a12", "select": "#2d5a3f",
        "border": "#3a3f45", "canvas": "#151719", "error": "#ff6b6b", "warn": "#f0b429",
        "ok": "#3ddc84", "cmd": "#7aa2f7", "header": "#3ddc84",
    },
    "light": {
        "bg": "#f3f4f6", "panel": "#ffffff", "field": "#ffffff", "fg": "#1d2024",
        "dim": "#6b7178", "accent": "#16a34a", "accent_fg": "#ffffff", "select": "#cdeed8",
        "border": "#cfd3d8", "canvas": "#e4e6e9", "error": "#c62828", "warn": "#a86400",
        "ok": "#16803c", "cmd": "#2f5bb7", "header": "#16803c",
    },
}


def apply_theme(root: tk.Misc, name: str) -> dict:
    c = PALETTES.get(name, PALETTES["dark"])
    style = ttk.Style(root)
    style.theme_use("clam")
    font = ("Segoe UI", 9)
    style.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["field"],
                    bordercolor=c["border"], lightcolor=c["border"], darkcolor=c["border"],
                    troughcolor=c["panel"], focuscolor=c["accent"], font=font,
                    insertcolor=c["fg"], selectbackground=c["select"], selectforeground=c["fg"])
    style.map(".", foreground=[("disabled", c["dim"])])
    style.configure("TFrame", background=c["bg"])
    style.configure("Panel.TFrame", background=c["panel"])
    style.configure("TLabel", background=c["bg"], foreground=c["fg"])
    style.configure("Dim.TLabel", foreground=c["dim"])
    style.configure("Title.TLabel", font=("Segoe UI Semibold", 11))
    style.configure("Status.TLabel", background=c["panel"], foreground=c["dim"], padding=(6, 2))
    style.configure("TLabelframe", background=c["bg"], bordercolor=c["border"])
    style.configure("TLabelframe.Label", background=c["bg"], foreground=c["dim"])
    style.configure("TButton", background=c["field"], foreground=c["fg"], padding=(8, 3),
                    bordercolor=c["border"])
    style.map("TButton", background=[("active", c["select"]), ("disabled", c["panel"])])
    style.configure("Accent.TButton", background=c["accent"], foreground=c["accent_fg"],
                    font=("Segoe UI Semibold", 9))
    style.map("Accent.TButton", background=[("active", c["ok"]), ("disabled", c["panel"])])
    style.configure("Tool.TButton", padding=(6, 3))
    # clam draws the check mark / radio dot in indicatorforeground on an
    # indicatorbackground box; it ignores indicatorcolor.
    for widget in ("TCheckbutton", "TRadiobutton"):
        style.configure(widget, background=c["bg"], foreground=c["fg"],
                        indicatorbackground=c["field"], indicatorforeground=c["accent"],
                        upperbordercolor=c["border"], lowerbordercolor=c["border"])
        style.map(widget, background=[("active", c["bg"])],
                  indicatorbackground=[("disabled", c["panel"]), ("pressed", c["select"])],
                  indicatorforeground=[("disabled", c["dim"])])
    style.configure("TEntry", fieldbackground=c["field"], foreground=c["fg"])
    style.configure("TSpinbox", fieldbackground=c["field"], foreground=c["fg"],
                    arrowcolor=c["fg"], background=c["field"])
    style.configure("TCombobox", fieldbackground=c["field"], foreground=c["fg"],
                    arrowcolor=c["fg"], background=c["field"])
    style.map("TCombobox", fieldbackground=[("readonly", c["field"])],
              foreground=[("readonly", c["fg"])])
    style.configure("TNotebook", background=c["bg"], bordercolor=c["border"])
    style.configure("TNotebook.Tab", background=c["panel"], foreground=c["dim"], padding=(10, 4))
    style.map("TNotebook.Tab", background=[("selected", c["bg"])],
              foreground=[("selected", c["fg"])])
    style.configure("Treeview", background=c["panel"], fieldbackground=c["panel"],
                    foreground=c["fg"], rowheight=24, bordercolor=c["border"])
    style.map("Treeview", background=[("selected", c["select"])],
              foreground=[("selected", c["fg"])])
    style.configure("Treeview.Heading", background=c["field"], foreground=c["dim"],
                    relief="flat", padding=(4, 3))
    style.map("Treeview.Heading", background=[("active", c["select"])])
    style.configure("Horizontal.TProgressbar", background=c["accent"], troughcolor=c["field"],
                    bordercolor=c["border"], lightcolor=c["accent"], darkcolor=c["accent"])
    style.configure("TScale", background=c["bg"], troughcolor=c["field"])
    style.configure("TPanedwindow", background=c["border"])
    style.configure("TSeparator", background=c["border"])
    style.configure("Vertical.TScrollbar", background=c["field"], troughcolor=c["bg"],
                    arrowcolor=c["fg"], bordercolor=c["bg"])
    style.configure("Horizontal.TScrollbar", background=c["field"], troughcolor=c["bg"],
                    arrowcolor=c["fg"], bordercolor=c["bg"])

    root.configure(background=c["bg"])
    root.option_add("*Menu.background", c["panel"])
    root.option_add("*Menu.foreground", c["fg"])
    root.option_add("*Menu.activeBackground", c["select"])
    root.option_add("*Menu.activeForeground", c["fg"])
    root.option_add("*Menu.relief", "flat")
    root.option_add("*TCombobox*Listbox.background", c["field"])
    root.option_add("*TCombobox*Listbox.foreground", c["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["select"])
    root.option_add("*TCombobox*Listbox.selectForeground", c["fg"])
    return c

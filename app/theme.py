"""界面主题：优先 sv-ttk（Windows 11 风格），失败则回退 clam + 自定义配色。"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

ACCENT = "#2F6FED"
BG = "#F5F6F8"
FG = "#1F2937"


def apply_theme(root: tk.Tk) -> str:
    style = ttk.Style(root)
    used = "clam"
    try:
        import sv_ttk  # type: ignore
        sv_ttk.set_theme("light")
        used = "sv-ttk"
    except Exception:  # noqa: BLE001
        try:
            style.theme_use("clam")
        except Exception:  # noqa: BLE001
            pass
        _fallback(style)
    _fonts()
    _common(style)
    try:
        root.configure(bg=BG)
    except Exception:  # noqa: BLE001
        pass
    return used


def _fonts() -> None:
    family = "Microsoft YaHei UI"
    for name, size in (("TkDefaultFont", 10), ("TkTextFont", 10), ("TkMenuFont", 10),
                       ("TkHeadingFont", 10)):
        try:
            f = tkfont.nametofont(name)
            f.configure(family=family, size=size)
        except Exception:  # noqa: BLE001
            pass
    try:
        tkfont.nametofont("TkHeadingFont").configure(weight="bold")
    except Exception:  # noqa: BLE001
        pass


def _fallback(style: ttk.Style) -> None:
    style.configure(".", background=BG, foreground=FG)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("TLabelframe", background=BG)
    style.configure("TLabelframe.Label", background=BG, foreground=ACCENT,
                    font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("TButton", padding=(10, 4))
    style.map("TButton", background=[("active", "#E5E7EB")])
    style.configure("TCheckbutton", background=BG)
    style.configure("TEntry", padding=3)
    style.configure("TCombobox", padding=3)


def _common(style: ttk.Style) -> None:
    try:
        style.configure("Treeview", rowheight=26, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))
    except Exception:  # noqa: BLE001
        pass
    try:
        style.configure("TNotebook.Tab", padding=(12, 5))
    except Exception:  # noqa: BLE001
        pass
    try:
        style.configure("Status.TLabel", foreground="#6B7280")
    except Exception:  # noqa: BLE001
        pass

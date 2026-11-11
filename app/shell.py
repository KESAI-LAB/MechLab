"""主壳：标题栏 + 模块标签页（提交器 / 文献→报告）。

以后加新模块：在 build() 里 import 页面类并加入 pages 列表即可。
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .config import APP_NAME, APP_VERSION
from .theme import apply_theme


def _asset(name: str) -> Path | None:
    p = Path(__file__).resolve().parent / "assets" / name
    return p if p.is_file() else None


def build(root: tk.Tk) -> list:
    """构建主窗口内容，返回模块页列表（便于测试）。"""
    apply_theme(root)
    root.title(f"{APP_NAME} {APP_VERSION}  ·  任务提交 / 文献报告  ·  KESAI")
    root.geometry("1280x900")
    root.minsize(1120, 740)
    icon = _asset("mechlab.ico")
    if icon is not None:
        try:
            root.iconbitmap(default=str(icon))
        except Exception:  # noqa: BLE001
            pass

    header = tk.Frame(root, bg="#111827", height=58)
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(header, text=APP_NAME, bg="#111827", fg="#FFFFFF",
             font=("Microsoft YaHei UI", 15, "bold")).pack(side="left", padx=(14, 6))
    tk.Label(header, text=f"{APP_VERSION}   ·   COMSOL 提交   ·   文献 → 报告",
             bg="#111827", fg="#9CA3AF", font=("Microsoft YaHei UI", 9)).pack(side="left", pady=(4, 0))
    # 小水印（跟在副标题后，灰色小字）
    tk.Label(header, text="·  KESAI", bg="#111827", fg="#6B7280",
             font=("Segoe UI", 9)).pack(side="left", padx=(18, 0), pady=(4, 0))

    # 底部水印条
    footer = tk.Frame(root, bg="#111827", height=20)
    footer.pack(side="bottom", fill="x")
    footer.pack_propagate(False)
    tk.Label(footer, text="KESAI", bg="#111827", fg="#6B7280",
             font=("Segoe UI", 8)).pack(side="left", padx=12)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=8, pady=8)

    from .modules.papers.ui import PapersPage
    from .modules.submitter.ui import SubmitterPage

    pages = [SubmitterPage(notebook), PapersPage(notebook)]
    for page in pages:
        notebook.add(page, text=page.title)

    def on_close() -> None:
        for page in pages:
            fn = getattr(page, "on_app_close", None)
            if fn is not None and fn() is False:
                return
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    return pages


def main() -> None:
    root = tk.Tk()
    build(root)
    root.mainloop()


if __name__ == "__main__":
    main()

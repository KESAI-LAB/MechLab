"""通知设置对话框（Bark）。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from . import notify


def open_notify_settings(parent) -> None:
    win = tk.Toplevel(parent)
    win.title("通知设置 · Bark")
    win.transient(parent)
    win.grab_set()
    win.resizable(False, False)

    cfg = notify.load()
    enabled = tk.BooleanVar(value=bool(cfg.get("enabled", True)))
    key = tk.StringVar(value=cfg.get("bark_key", ""))
    server = tk.StringVar(value=cfg.get("bark_server", "https://api.day.app"))
    group = tk.StringVar(value=cfg.get("group", "MechLab"))
    ttl = tk.StringVar(value=str(cfg.get("ttl", 600)))
    on_done = tk.BooleanVar(value=bool(cfg.get("notify_done", True)))
    on_fail = tk.BooleanVar(value=bool(cfg.get("notify_failed", True)))
    hint = tk.StringVar(value="")

    body = ttk.Frame(win, padding=14)
    body.pack(fill="both", expand=True)
    body.columnconfigure(1, weight=1)

    ttk.Checkbutton(body, text="启用任务通知（Bark）", variable=enabled).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
    ttk.Label(body, text="Bark Key").grid(row=1, column=0, sticky="w", pady=3)
    ttk.Entry(body, textvariable=key, width=46, show="•").grid(
        row=1, column=1, sticky="we", pady=3)
    ttk.Label(body, text="服务器").grid(row=2, column=0, sticky="w", pady=3)
    ttk.Entry(body, textvariable=server, width=46).grid(
        row=2, column=1, sticky="we", pady=3)
    ttk.Label(body, text="分组").grid(row=3, column=0, sticky="w", pady=3)
    ttk.Entry(body, textvariable=group, width=20).grid(
        row=3, column=1, sticky="w", pady=3)
    ttk.Label(body, text="保留秒数").grid(row=4, column=0, sticky="w", pady=3)
    ttk.Entry(body, textvariable=ttl, width=12).grid(
        row=4, column=1, sticky="w", pady=3)
    ttk.Checkbutton(body, text="完成时通知", variable=on_done).grid(
        row=5, column=1, sticky="w", pady=2)
    ttk.Checkbutton(body, text="失败时通知", variable=on_fail).grid(
        row=6, column=1, sticky="w", pady=2)
    ttk.Label(body, textvariable=hint, foreground="#6b7280").grid(
        row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def collect() -> dict | None:
        k = key.get().strip()
        if enabled.get() and not k:
            messagebox.showwarning("通知", "启用通知需要填写 Bark Key", parent=win)
            return None
        try:
            ttl_v = int(ttl.get().strip() or "600")
        except ValueError:
            ttl_v = 600
        return {
            "enabled": bool(enabled.get()),
            "bark_key": k,
            "bark_server": server.get().strip() or "https://api.day.app",
            "group": group.get().strip() or "MechLab",
            "ttl": max(0, ttl_v),
            "notify_done": bool(on_done.get()),
            "notify_failed": bool(on_fail.get()),
        }

    def do_save() -> None:
        data = collect()
        if data is None:
            return
        notify.save(data)
        hint.set("已保存")
        win.after(600, win.destroy)

    def do_test() -> None:
        data = collect()
        if data is None:
            return
        notify.save(data)
        hint.set("发送中…")
        win.update_idletasks()

        def work():
            ok = notify.test(data)
            def finish():
                hint.set("已发送，请查看手机" if ok else "发送失败（检查 Key/网络）")
            win.after(0, finish)

        import threading
        threading.Thread(target=work, daemon=True).start()

    btns = ttk.Frame(body)
    btns.grid(row=8, column=0, columnspan=2, sticky="e", pady=(12, 0))
    ttk.Button(btns, text="测试", command=do_test).pack(side="left", padx=4)
    ttk.Button(btns, text="取消", command=win.destroy).pack(side="left", padx=4)
    ttk.Button(btns, text="保存", command=do_save).pack(side="left", padx=4)

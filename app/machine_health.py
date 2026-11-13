"""机器健康面板：并发探测本机/远程机器，显示在线、COMSOL、延迟、队列。"""
from __future__ import annotations

import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk

from .backends import get_backend
from .config import MACHINES, REPO
from .runner import CREATE_NO_WINDOW, find_bash

REFRESH_MS = 30_000


def check_machine(key: str, timeout: int = 25) -> dict:
    machine = MACHINES.get(key)
    if machine is None:
        return {"key": key, "label": key, "online": False, "comsol": False,
                "ms": 0.0, "note": "未定义"}
    t0 = time.time()
    try:
        cmd = get_backend(machine.backend, key).build_probe_command()
        r = subprocess.run(
            [find_bash(), "-lc", cmd], cwd=str(REPO),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=CREATE_NO_WINDOW)
        out = (r.stdout or "") + (r.stderr or "")
        rc = r.returncode
    except Exception as exc:  # noqa: BLE001
        out = f"[probe] {exc}"
        rc = -1
    ms = (time.time() - t0) * 1000

    online = any(tag in out for tag in ("LINK_OK", "COMSOL_OK", "COMSOL_MISSING", "MOCK_OK"))
    comsol = "COMSOL_OK" in out
    note = ""
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("host="):
            note = s
        elif "本机核数" in s and not note:
            note = s
    if "MOCK_OK" in out:
        note = "演示模式（不连远程）"
    elif online and not note:
        note = "已连接"
    if not online:
        errs = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("#")]
        note = (errs[-1] if errs else f"exit {rc}")[:100]
    return {"key": key, "label": machine.label, "online": online,
            "comsol": comsol, "ms": ms, "note": note}


def _queue_text(manager, key: str) -> str:
    try:
        jobs = list(manager.jobs.values()) if manager else []
    except Exception:  # noqa: BLE001
        jobs = []
    running = sum(1 for j in jobs if j.machine == key and j.status == "running")
    waiting = sum(1 for j in jobs if j.machine == key and j.status in ("pending", "staged"))
    return f"运行 {running} · 待跑 {waiting}"


def open_machine_health(parent, manager) -> None:
    win = tk.Toplevel(parent)
    win.title("机器健康")
    win.transient(parent)
    win.geometry("860x260")
    win.minsize(720, 220)

    frame = ttk.Frame(win, padding=10)
    frame.pack(fill="both", expand=True)

    cols = ("machine", "state", "comsol", "ms", "queue", "checked", "note")
    tree = ttk.Treeview(frame, columns=cols, show="headings", height=len(MACHINES))
    heads = {"machine": "机器", "state": "状态", "comsol": "COMSOL",
             "ms": "延迟", "queue": "队列", "checked": "检查时间", "note": "备注"}
    widths = {"machine": 150, "state": 70, "comsol": 80, "ms": 80,
              "queue": 110, "checked": 80, "note": 270}
    for c in cols:
        tree.heading(c, text=heads[c])
        tree.column(c, width=widths[c], anchor="w")
    tree.pack(fill="both", expand=True)
    tree.tag_configure("online", foreground="#0a6")
    tree.tag_configure("warn", foreground="#a60")
    tree.tag_configure("offline", foreground="#c33")

    bottom = ttk.Frame(frame)
    bottom.pack(fill="x", pady=(8, 0))
    hint = tk.StringVar(value="准备检查…")
    ttk.Label(bottom, textvariable=hint, foreground="#6b7280").pack(side="left")
    auto = tk.BooleanVar(value=True)

    def refresh() -> None:
        if not win.winfo_exists():
            return
        for key in MACHINES:
            values = (MACHINES[key].label, "检查中…", "", "", "", "", "")
            if tree.exists(key):
                tree.item(key, values=values, tags=())
            else:
                tree.insert("", "end", iid=key, values=values)
        hint.set("正在检查…")

        results: dict[str, dict] = {}
        threads = []
        for key in MACHINES:
            t = threading.Thread(target=lambda k=key: results.__setitem__(k, check_machine(k)),
                                 daemon=True)
            t.start()
            threads.append(t)

        def collect() -> None:
            if not win.winfo_exists():
                return
            if any(t.is_alive() for t in threads):
                win.after(200, collect)
                return
            online_n = 0
            for key in MACHINES:
                r = results.get(key) or {"label": MACHINES[key].label, "online": False,
                                         "comsol": False, "ms": 0.0, "note": "无结果"}
                state = "在线" if r["online"] else "离线"
                if r["comsol"]:
                    comsol = "OK"
                elif not r["online"] or key == "M":
                    comsol = "—"
                else:
                    comsol = "MISSING"
                tag = "online" if r["online"] else "offline"
                if r["online"] and not r["comsol"]:
                    tag = "warn"
                values = (r["label"], state, comsol, f"{r['ms']:.0f} ms",
                          _queue_text(manager, key), time.strftime("%H:%M:%S"),
                          (r.get("note") or "")[:110])
                if tree.exists(key):
                    tree.item(key, values=values, tags=(tag,))
                if r["online"]:
                    online_n += 1
            hint.set(f"{online_n}/{len(MACHINES)} 台在线 · 每 30 秒自动刷新")
            if auto.get():
                win.after(REFRESH_MS, refresh)

        win.after(100, collect)

    ttk.Button(bottom, text="立即刷新", command=refresh).pack(side="right", padx=4)
    ttk.Button(bottom, text="关闭", command=win.destroy).pack(side="right", padx=4)
    ttk.Checkbutton(bottom, text="自动刷新（30s）", variable=auto).pack(side="right", padx=10)

    refresh()

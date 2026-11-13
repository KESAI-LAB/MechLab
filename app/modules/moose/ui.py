"""MOOSE 提交模块：WSL 本地运行 .i 模型，队列 / 日志 / 中止 / 通知。"""
from __future__ import annotations

import os
import posixpath
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from ..base import BaseModule
from .runner import (LOG_DIR, STATUS_COLOR, STATUS_TXT, MooseJob, MooseManager,
                     default_distro, load_settings, new_job_id, resolve_path,
                     save_settings, to_wsl_path, wsl_test)

#: 常用 MOOSE 参数（下拉菜单里点一下自动追加）
EXTRA_PRESETS = [
    ("--recover", "断点续算"),
    ("--mesh-only", "只生成网格"),
    ("--check-input", "只检查输入"),
    ("--show-input", "打印解析后的输入"),
    ("--error", "警告当错误"),
    ("--no-color", "关闭彩色输出"),
    ("--keep-cout", "并行保留各进程输出"),
    ("--distributed-mesh", "强制分布式网格"),
    ("--show-outputs", "显示输出耗时"),
    ("--suppress-header", "不打印 App 头部"),
]


class MoosePage(BaseModule):
    title = "MOOSE 提交"

    def __init__(self, master):
        super().__init__(master)
        self.manager = MooseManager()
        self._selected: str | None = None
        self._log_sig: tuple | None = None
        self._settings = load_settings()
        self._build_ui()
        self.after(700, self._poll)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=3)
        self.rowconfigure(3, weight=2)

        form = ttk.LabelFrame(self, text="MOOSE 任务（WSL 本地）")
        form.grid(row=0, column=0, sticky="ew", **pad)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(4, weight=1)

        distro = self._settings.get("distro") or default_distro()
        ttk.Label(form, text="WSL 发行版").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self.distro_var = tk.StringVar(value=distro)
        ttk.Entry(form, textvariable=self.distro_var, width=18).grid(
            row=0, column=1, sticky="w", padx=4, pady=3)

        ttk.Label(form, text="MOOSE App").grid(row=0, column=2, sticky="e", padx=(12, 4), pady=3)
        self.app_var = tk.StringVar(value=self._settings.get("app", ""))
        ttk.Entry(form, textvariable=self.app_var).grid(
            row=0, column=3, columnspan=3, sticky="ew", padx=4, pady=3)

        ttk.Label(form, text="输入文件 .i").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        self.input_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.input_var).grid(
            row=1, column=1, columnspan=3, sticky="ew", padx=4, pady=3)
        ttk.Button(form, text="浏览…", command=self.browse_input).grid(
            row=1, column=4, sticky="w", padx=4, pady=3)

        ttk.Label(form, text="工作目录").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        self.workdir_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.workdir_var).grid(
            row=2, column=1, columnspan=3, sticky="ew", padx=4, pady=3)

        ttk.Label(form, text="MPI 命令").grid(row=3, column=0, sticky="w", padx=4, pady=3)
        self.mpi_var = tk.StringVar(value=self._settings.get("mpi_cmd", ""))
        ttk.Entry(form, textvariable=self.mpi_var).grid(
            row=3, column=1, sticky="ew", padx=4, pady=3)
        ttk.Label(form, text="（留空=串行；有 mpiexec 可填 mpiexec -n 8）",
                  foreground="#6b7280").grid(row=3, column=2, columnspan=2, sticky="w")

        ttk.Label(form, text="线程数").grid(row=4, column=0, sticky="w", padx=4, pady=3)
        self.threads_var = tk.StringVar(value=str(self._settings.get("threads", 1)))
        ttk.Spinbox(form, from_=1, to=64, width=6, textvariable=self.threads_var).grid(
            row=4, column=1, sticky="w", padx=4, pady=3)
        ttk.Label(form, text="环境命令").grid(row=4, column=2, sticky="e", padx=(12, 4), pady=3)
        self.env_var = tk.StringVar(value=self._settings.get("env_cmd", ""))
        ttk.Entry(form, textvariable=self.env_var).grid(
            row=4, column=3, columnspan=2, sticky="ew", padx=4, pady=3)

        ttk.Label(form, text="额外参数").grid(row=5, column=0, sticky="w", padx=4, pady=3)
        extra_wrap = ttk.Frame(form)
        extra_wrap.grid(row=5, column=1, sticky="ew", padx=4, pady=3)
        extra_wrap.columnconfigure(0, weight=1)
        self.extra_var = tk.StringVar(value=self._settings.get("extra", ""))
        ttk.Entry(extra_wrap, textvariable=self.extra_var).grid(row=0, column=0, sticky="ew")
        mb = ttk.Menubutton(extra_wrap, text="常用参数 ▾")
        menu = tk.Menu(mb, tearoff=False)
        for flag, label in EXTRA_PRESETS:
            menu.add_command(label=f"{label}（{flag}）",
                             command=lambda f=flag: self._append_extra(f))
        menu.add_separator()
        menu.add_command(label="自定义…", command=self._custom_extra)
        menu.add_command(label="清空额外参数", command=lambda: self.extra_var.set(""))
        mb["menu"] = menu
        mb.grid(row=0, column=1, padx=(6, 0))
        ttk.Label(form, text="标签").grid(row=5, column=2, sticky="e", padx=(12, 4), pady=3)
        self.tag_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.tag_var, width=18).grid(
            row=5, column=3, sticky="w", padx=4, pady=3)

        btns = ttk.Frame(self)
        btns.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))
        ttk.Button(btns, text="▶ 提交计算", command=self.submit).pack(side="left")
        ttk.Button(btns, text="■ 中止选中", command=self.cancel_selected).pack(side="left", padx=(14, 4))
        ttk.Button(btns, text="✕ 移除选中", command=self.remove_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="清空已完成", command=self.clear_finished).pack(side="left", padx=4)
        ttk.Button(btns, text="打开日志目录", command=self.open_logs).pack(side="left", padx=(14, 4))
        self.status_var = tk.StringVar(value="就绪：选择 .i 文件后提交")
        ttk.Label(btns, textvariable=self.status_var, foreground="#0a6").pack(side="right", padx=8)

        table = ttk.LabelFrame(self, text="任务队列（排队 → 运行 → 完成）")
        table.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 6))
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        cols = ("id", "input", "status", "progress", "elapsed", "outputs", "error")
        self.tree = ttk.Treeview(table, columns=cols, show="headings", height=7,
                                 selectmode="browse")
        heads = {"id": "ID", "input": "输入文件", "status": "状态", "progress": "进度",
                 "elapsed": "耗时", "outputs": "输出 CSV", "error": "错误摘要"}
        widths = {"id": 66, "input": 260, "status": 76, "progress": 230,
                  "elapsed": 66, "outputs": 150, "error": 260}
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor="w")
        ys = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        for status, color in STATUS_COLOR.items():
            self.tree.tag_configure(status, foreground=color)

        logf = ttk.LabelFrame(self, text="日志（选中任务）")
        logf.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
        logf.rowconfigure(0, weight=1)
        logf.columnconfigure(0, weight=1)
        self.log_text = tk.Text(logf, height=10, wrap="none", state="disabled",
                                font=("Consolas", 9))
        lys = ttk.Scrollbar(logf, orient="vertical", command=self.log_text.yview)
        lxs = ttk.Scrollbar(logf, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=lys.set, xscrollcommand=lxs.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        lys.grid(row=0, column=1, sticky="ns")
        lxs.grid(row=1, column=0, sticky="ew")

    def _append_extra(self, flag: str) -> None:
        cur = self.extra_var.get().strip()
        tokens = cur.split()
        if flag in tokens:
            return
        self.extra_var.set((cur + " " + flag).strip())

    def _custom_extra(self) -> None:
        value = simpledialog.askstring(
            "额外参数", "输入要追加的 MOOSE 参数（可多个，空格分隔）：", parent=self)
        if value and value.strip():
            self._append_extra(value.strip())

    def browse_input(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="选择 MOOSE 输入文件",
            filetypes=[("MOOSE 输入", "*.i"), ("所有文件", "*.*")])
        if not path:
            return
        self.input_var.set(path)
        wsl_path = to_wsl_path(path)
        self.workdir_var.set(posixpath.dirname(wsl_path) if wsl_path.startswith("/") else "")
        if not self.tag_var.get().strip():
            self.tag_var.set(Path(path).stem)

    def _collect(self) -> MooseJob | None:
        distro = self.distro_var.get().strip()
        app = self.app_var.get().strip()
        raw_input = self.input_var.get().strip()
        if not distro:
            messagebox.showwarning("MOOSE", "请填写 WSL 发行版（如 Ubuntu-24.04）", parent=self)
            return None
        if not app:
            messagebox.showwarning("MOOSE", "请填写 MOOSE App 路径", parent=self)
            return None
        if not raw_input:
            messagebox.showwarning("MOOSE", "请选择 .i 输入文件", parent=self)
            return None

        input_wsl = resolve_path(raw_input, distro)
        if not wsl_test(distro, "-f", input_wsl):
            messagebox.showwarning("MOOSE", f"WSL 里找不到输入文件：\n{input_wsl}", parent=self)
            return None
        app_wsl = resolve_path(app, distro)
        if not wsl_test(distro, "-x", app_wsl):
            if not messagebox.askyesno(
                    "MOOSE", f"WSL 里这个 App 不可执行：\n{app_wsl}\n\n仍要提交吗？", parent=self):
                return None
        workdir = self.workdir_var.get().strip() or posixpath.dirname(input_wsl)
        try:
            threads = max(1, int(self.threads_var.get().strip() or "1"))
        except ValueError:
            threads = 1
        job = MooseJob(
            id=new_job_id(),
            input_file=raw_input,
            input_wsl=input_wsl,
            workdir_wsl=workdir,
            app=app_wsl,
            distro=distro,
            mpi_cmd=self.mpi_var.get().strip(),
            threads=threads,
            env_cmd=self.env_var.get().strip(),
            extra=self.extra_var.get().strip(),
            tag=self.tag_var.get().strip() or posixpath.splitext(posixpath.basename(input_wsl))[0],
        )
        save_settings({
            "distro": distro, "app": app,
            "mpi_cmd": job.mpi_cmd, "threads": threads,
            "env_cmd": job.env_cmd, "extra": job.extra,
        })
        return job

    def submit(self) -> None:
        job = self._collect()
        if job is None:
            return
        self.manager.add(job)
        self.status_var.set(f"已提交 {job.id}：{posixpath.basename(job.input_wsl)}")
        self._selected = job.id
        self._log_sig = None
        if self.tree.exists(job.id):
            self.tree.selection_set(job.id)
        self.refresh()

    def cancel_selected(self) -> None:
        jid = self._selected
        if not jid:
            return
        if messagebox.askyesno("中止", "中止选中的计算？", parent=self):
            self.manager.cancel(jid)
            self.refresh()

    def remove_selected(self) -> None:
        if self._selected:
            self.manager.remove(self._selected)
            self._selected = None
            self.refresh()

    def clear_finished(self) -> None:
        self.manager.clear_finished()
        self.refresh()

    def open_logs(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(LOG_DIR))  # noqa: S606
        except Exception:  # noqa: BLE001
            messagebox.showinfo("日志目录", str(LOG_DIR), parent=self)

    def on_select(self, *_) -> None:
        sel = self.tree.selection()
        self._selected = sel[0] if sel else None
        self._log_sig = None
        self._show_log()

    # ------------------------------------------------------------------ 刷新
    def _poll(self) -> None:
        try:
            self.refresh()
            self._show_log()
        finally:
            self.after(700, self._poll)

    def refresh(self) -> None:
        jobs = sorted(self.manager.jobs.values(), key=lambda j: j.created, reverse=True)
        seen = set()
        for j in jobs:
            seen.add(j.id)
            out = ""
            if j.outputs:
                out = Path(j.outputs[0]).name + (f" (+{len(j.outputs) - 1})" if len(j.outputs) > 1 else "")
            vals = (j.id, posixpath.basename(j.input_wsl), STATUS_TXT.get(j.status, j.status),
                    j.progress, f"{int(j.elapsed)} s" if j.elapsed else "",
                    out, j.error[:80] if j.error else "")
            if self.tree.exists(j.id):
                self.tree.item(j.id, values=vals, tags=(j.status,))
            else:
                self.tree.insert("", "end", iid=j.id, values=vals, tags=(j.status,))
        for iid in self.tree.get_children():
            if iid not in seen:
                self.tree.delete(iid)

    def _show_log(self) -> None:
        jid = self._selected
        if not jid:
            return
        job = self.manager.jobs.get(jid)
        if not job or not job.log_path:
            return
        try:
            st = os.stat(job.log_path)
        except OSError:
            return
        sig = (job.log_path, st.st_mtime, st.st_size)
        if sig == self._log_sig:
            return
        self._log_sig = sig
        try:
            text = Path(job.log_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        lines = text.splitlines()[-250:]
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "\n".join(lines))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------ 关闭
    def on_app_close(self) -> bool:
        busy = self.manager.machine_busy()
        if busy:
            if not messagebox.askyesno(
                    "MOOSE 正在运行", f"任务 {busy.id} 还在运行，退出会中止它。确定退出？",
                    parent=self):
                return False
            self.manager.cancel(busy.id)
        return True

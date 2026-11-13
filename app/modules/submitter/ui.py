"""主界面：文件夹浏览 + 待提交队列 + 任务表 + 日志 + 连接测试 + 中止。

区域：
    顶部  新建任务（模型 / 机器 / 核数 / 研究步 / 标签 / 探针 / 保存全部解）
    中部  左：模型文件夹列表；右：任务表（待提交 / 排队 / 运行 / 完成…）
    按钮  加入队列、批量加入、提交选中、提交全部、中止、移除、清空
    底部  日志（可折叠、精简/完整）
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ...backends import Job as JobInput, get_backend
from ...config import (DEFAULT_SPEC, DEFAULT_SPEC_DOMAIN_ONLY, MACHINE_BY_LABEL,
                       MACHINES, REPO, label_list)
from ...manager import Manager
from ...runner import CREATE_NO_WINDOW, find_bash
from ... import machines as machines_mod
from ...machine_ui import open_machine_setup
from ...machine_health import open_machine_health
from ...notify_ui import open_notify_settings
from ..base import BaseModule

STATUS_TXT = {
    "staged": "待提交", "pending": "排队中", "running": "运行中",
    "done": "完成 ✓", "failed": "失败 ✗", "cancelled": "已中止", "interrupted": "中断",
}
STATUS_COLOR = {
    "staged": "#444", "pending": "#8a6d00", "running": "#0a6", "done": "#0a6",
    "failed": "#c33", "cancelled": "#777", "interrupted": "#c60",
}


class SubmitterPage(BaseModule):
    """COMSOL 提交（原主界面整体搬入模块）。"""

    title = "COMSOL 提交"

    def __init__(self, master):
        super().__init__(master)
        self.root = self.winfo_toplevel()
        machines_mod.load_into_config()
        self.manager = Manager()
        self.selected: str | None = None
        self._log_sig = None

        pad = {"padx": 10, "pady": 6}


        # ================= 顶部：新建任务 =================
        form = ttk.LabelFrame(self, text="新建任务")
        form.pack(fill="x", **pad)

        ttk.Label(form, text="模型").grid(row=0, column=0, sticky="w", padx=(8, 2), pady=4)
        self.model_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.model_var, width=70).grid(
            row=0, column=1, columnspan=4, sticky="we", padx=4)
        ttk.Button(form, text="浏览…", command=self.browse_model).grid(row=0, column=5, padx=(2, 8))

        ttk.Label(form, text="提交到").grid(row=1, column=0, sticky="w", padx=(8, 2))
        self.machine_var = tk.StringVar(value=label_list()[0])
        cb = ttk.Combobox(form, textvariable=self.machine_var, values=label_list(),
                          state="readonly", width=16)
        self.machine_cb = cb
        cb.grid(row=1, column=1, sticky="w", padx=4)
        cb.bind("<<ComboboxSelected>>", self.on_machine)
        ttk.Label(form, text="核数").grid(row=1, column=2, sticky="e")
        self.cores_var = tk.IntVar(value=8)
        ttk.Spinbox(form, from_=1, to=128, textvariable=self.cores_var, width=6).grid(
            row=1, column=3, sticky="w", padx=4)
        ttk.Label(form, text="研究步").grid(row=1, column=4, sticky="e")
        self.study_var = tk.StringVar(value="std1")
        ttk.Entry(form, textvariable=self.study_var, width=14).grid(row=1, column=5, sticky="w", padx=(4, 2))
        ttk.Label(form, text="标签").grid(row=1, column=6, sticky="e")
        self.tag_var = tk.StringVar(value=time.strftime("%m%d_%H%M"))
        ttk.Entry(form, textvariable=self.tag_var, width=12).grid(row=1, column=7, sticky="w", padx=(4, 2))
        self.save_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="保存全部解", variable=self.save_var,
                        command=self.update_save_hint).grid(
            row=1, column=8, sticky="w", padx=(8, 4))
        self.save_hint = ttk.Label(form, text="", foreground="#06c", font=("Consolas", 8))
        self.save_hint.grid(row=1, column=9, sticky="w", padx=(0, 8))

        ttk.Label(form, text="探针").grid(row=2, column=0, sticky="w", padx=(8, 2))
        self.spec_text = tk.Text(form, height=3, width=110, wrap="word")
        self.spec_text.insert("1.0", DEFAULT_SPEC)
        self.spec_text.grid(row=2, column=1, columnspan=7, sticky="we", padx=4, pady=(0, 2))
        ttk.Label(form,
                  text="域=数字（2,3,4）；边界=b 前缀（b13,18，仅 K/A）；研究步留空=全部，逗号=按顺序；"
                       "“保存全部解”会把解模型写到该机器的 solutions 目录",
                  foreground="#666").grid(row=3, column=0, columnspan=9, sticky="w", padx=8)
        form.columnconfigure(1, weight=1)

        # ================= 机器状态条 =================
        stat = ttk.Frame(self)
        stat.pack(fill="x", **pad)
        self.stat_frame = stat
        self.machine_labels: dict[str, ttk.Label] = {}
        self._build_machine_bar()

        # ================= 中部：文件夹 + 任务表 =================
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, **pad)
        mid.columnconfigure(1, weight=1)
        mid.rowconfigure(0, weight=1)

        # --- 左：文件夹浏览 ---
        left = ttk.LabelFrame(mid, text="模型文件夹")
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 6))
        self.folder_var = tk.StringVar(value="")
        frow = ttk.Frame(left)
        frow.pack(fill="x", padx=4, pady=4)
        ttk.Entry(frow, textvariable=self.folder_var, width=26).pack(side="left", fill="x", expand=True)
        ttk.Button(frow, text="…", width=3, command=self.browse_folder).pack(side="left", padx=(2, 0))
        ttk.Button(frow, text="刷新", width=5, command=self.refresh_files).pack(side="left", padx=(2, 0))

        fl = ttk.Frame(left)
        fl.pack(fill="both", expand=True, padx=4)
        self.file_list = tk.Listbox(fl, selectmode="extended", width=34, height=14,
                                    exportselection=False, activestyle="none")
        fs = ttk.Scrollbar(fl, orient="vertical", command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=fs.set)
        self.file_list.pack(side="left", fill="both", expand=True)
        fs.pack(side="left", fill="y")

        btns = ttk.Frame(left)
        btns.pack(fill="x", padx=4, pady=4)
        ttk.Button(btns, text="加入选中", command=self.add_selected_files).pack(side="left")
        ttk.Button(btns, text="全部加入", command=self.add_all_files).pack(side="left", padx=4)

        # --- 右：任务表 ---
        right = ttk.LabelFrame(mid, text="任务队列（待提交 → 排队 → 运行）")
        right.grid(row=0, column=1, sticky="nsew")
        cols = ("id", "machine", "model", "tag", "cores", "study", "save", "status", "err", "progress", "elapsed")
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=10, selectmode="extended")
        heads = {"id": "ID", "machine": "机器", "model": "模型", "tag": "标签", "cores": "核数",
                 "study": "研究步", "save": "存解", "status": "状态", "err": "错误摘要",
                 "progress": "进度", "elapsed": "用时"}
        widths = {"id": 66, "machine": 62, "model": 220, "tag": 84, "cores": 44,
                  "study": 70, "save": 40, "status": 76, "err": 200,
                  "progress": 160, "elapsed": 62}
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor="w")
        ys = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        for s, col in STATUS_COLOR.items():
            self.tree.tag_configure(s, foreground=col)
        self.tree.tag_configure("stalled", background="#fff3cd")

        # ================= 操作按钮 =================
        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        ttk.Button(bar, text="＋ 加入队列(待提交)", command=self.enqueue_form).pack(side="left")
        ttk.Button(bar, text="▶ 提交选中", command=self.submit_selected).pack(side="left", padx=(14, 4))
        ttk.Button(bar, text="▶▶ 提交全部", command=self.submit_all).pack(side="left", padx=4)
        ttk.Button(bar, text="■ 中止选中", command=self.cancel_selected).pack(side="left", padx=(14, 4))
        ttk.Button(bar, text="✕ 移除选中", command=self.remove_selected).pack(side="left", padx=4)
        ttk.Button(bar, text="清空已完成", command=self.clear_finished).pack(side="left", padx=4)
        ttk.Button(bar, text="🔌 测试连接", command=self.probe).pack(side="left", padx=(14, 4))
        ttk.Button(bar, text="🩺 机器健康", command=lambda: open_machine_health(self, self.manager)).pack(
            side="left", padx=4)
        ttk.Button(bar, text="🔔 通知", command=lambda: open_notify_settings(self)).pack(
            side="left", padx=4)
        ttk.Button(bar, text="📈 一键画图（演示）", command=self.plot_demo).pack(side="left", padx=4)
        ttk.Button(bar, text="打开日志目录", command=self.open_logs).pack(side="left", padx=4)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(bar, textvariable=self.status_var, foreground="#0a6").pack(side="right", padx=8)

        # ================= 日志 =================
        self.log_frame = ttk.LabelFrame(self, text="任务日志（选中某行查看）")
        self.log_frame.pack(fill="both", expand=True, **pad)
        hdr = ttk.Frame(self.log_frame)
        hdr.grid(row=0, column=0, columnspan=2, sticky="we", padx=4, pady=(2, 0))
        self.full_log_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(hdr, text="完整日志（默认只看关键信息）",
                        variable=self.full_log_var).pack(side="left")
        self.log_toggle_btn = ttk.Button(hdr, text="收起日志 ▴", width=12, command=self.toggle_log)
        self.log_toggle_btn.pack(side="right")
        self.log_body = ttk.Frame(self.log_frame)
        self.log_body.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self.log = tk.Text(self.log_body, wrap="none", state="disabled", bg="#11161b", fg="#d7e3ec",
                           insertbackground="#d7e3ec", font=("Consolas", 9), height=10)
        lys = ttk.Scrollbar(self.log_body, orient="vertical", command=self.log.yview)
        lxs = ttk.Scrollbar(self.log_body, orient="horizontal", command=self.log.xview)
        self.log.configure(yscrollcommand=lys.set, xscrollcommand=lxs.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        lys.grid(row=0, column=1, sticky="ns")
        lxs.grid(row=1, column=0, sticky="we")
        self.log_body.rowconfigure(0, weight=1)
        self.log_body.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(1, weight=1)
        self.log_frame.columnconfigure(0, weight=1)
        self.log_collapsed = False

        self.on_machine()
        self.refresh()
        self.after(200, self.pump_logs)

    # ------------------------------------------------------------------ 基础
    def machine(self):
        return MACHINE_BY_LABEL[self.machine_var.get()]

    def on_machine(self, *_):
        m = self.machine()
        self.cores_var.set(m.cores)
        if m.key == "M":
            if not self.model_var.get().strip():
                demo = REPO / "examples" / "mock" / "demo_model.mph"
                if demo.exists():
                    self.model_var.set(str(demo))
            if not self.tag_var.get().strip():
                self.tag_var.set("tensile")
        spec = self.spec_text.get("1.0", "end")
        if not m.supports_boundary and "@b" in spec:
            self.spec_text.delete("1.0", "end")
            self.spec_text.insert("1.0", DEFAULT_SPEC_DOMAIN_ONLY)
        try:
            self.update_save_hint()
        except Exception:  # noqa: BLE001
            pass

    def _build_machine_bar(self) -> None:
        """重建机器状态条（支持运行时新增机器）。"""
        for w in self.stat_frame.winfo_children():
            w.destroy()
        self.machine_labels = {}
        for i, (k, m) in enumerate(MACHINES.items()):
            lb = ttk.Label(self.stat_frame, text=f"{m.label}：空闲", foreground="#0a6")
            lb.grid(row=0, column=i, sticky="w", padx=(8, 20))
            self.machine_labels[k] = lb
        ttk.Button(self.stat_frame, text="➕ 接入新机",
                   command=lambda: open_machine_setup(self)).grid(
            row=0, column=len(MACHINES), sticky="w", padx=(8, 8))

    def refresh_machines(self) -> None:
        """新机器保存后刷新下拉框与状态条。"""
        vals = label_list()
        self.machine_cb.configure(values=vals)
        if self.machine_var.get() not in vals:
            self.machine_var.set(vals[0])
        self._build_machine_bar()
        self.on_machine()

    def browse_model(self):
        p = filedialog.askopenfilename(title="选择 COMSOL 模型",
                                       filetypes=[("COMSOL 模型", "*.mph"), ("所有文件", "*.*")])
        if p:
            self.model_var.set(os.path.normpath(p))

    def browse_folder(self):
        d = filedialog.askdirectory(title="选择模型文件夹")
        if d:
            self.folder_var.set(os.path.normpath(d))
            self.refresh_files()

    def refresh_files(self):
        self.file_list.delete(0, "end")
        d = self.folder_var.get().strip()
        if not d or not os.path.isdir(d):
            return
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".mph"):
                self.file_list.insert("end", f)

    def selected_files(self) -> list[str]:
        d = self.folder_var.get().strip()
        if not d:
            return []
        return [os.path.join(d, self.file_list.get(i)) for i in self.file_list.curselection()]

    def update_save_hint(self):
        """勾选“保存全部解”时，显示解会存到哪里。"""
        if not self.save_var.get():
            self.save_hint.configure(text="")
            return
        k = self.machine().key
        if k == "K":
            d = os.path.dirname(os.path.abspath(self.model_var.get())) if self.model_var.get() else "<模型目录>"
            self.save_hint.configure(text="-> " + d + "\\solved\\<模型>_<标签>_solved.mph")
        else:
            self.save_hint.configure(
                text="-> 远程自动选非 C 盘（优先 D:\\...\\solutions；盘/目录不存在会自动创建）"
                     "\\<模型>_<标签>_solved.mph")

    def open_logs(self):
        from ...config import LOG_DIR
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(LOG_DIR))

    # ------------------------------------------------------------------ 入队
    def _job_from(self, model: str) -> JobInput:
        return JobInput(model=model,
                        spec=self.spec_text.get("1.0", "end").strip().replace("\n", ""),
                        study=self.study_var.get().strip(),
                        cores=int(self.cores_var.get()),
                        tag=self.tag_var.get().strip(),
                        save_solution=bool(self.save_var.get()))

    def _add_models(self, models: list[str]):
        if not models:
            messagebox.showinfo("没有模型", "先在左侧列表里选择模型（或先浏览文件夹）")
            return
        m = self.machine()
        ok, fail = 0, []
        for model in models:
            try:
                self.manager.add_job(m.key, self._job_from(model))
                ok += 1
            except ValueError as exc:
                fail.append(f"{os.path.basename(model)}: {exc}")
        msg = f"已加入 {ok} 个到【{m.label}】待提交队列"
        if fail:
            msg += f"；{len(fail)} 个失败"
            messagebox.showwarning("部分未加入", "\n".join(fail[:8]))
        self.status_var.set(msg + " — 确认后点“▶ 提交选中 / ▶▶ 提交全部”")
        self.refresh()

    def enqueue_form(self):
        model = self.model_var.get().strip()
        if not model:
            messagebox.showinfo("提示", "先选模型文件，或从左侧文件夹加入")
            return
        self._add_models([model])

    def add_selected_files(self):
        self._add_models(self.selected_files())

    def add_all_files(self):
        d = self.folder_var.get().strip()
        if not d:
            messagebox.showinfo("提示", "先选择模型文件夹")
            return
        models = [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith(".mph")]
        self._add_models(models)

    # ------------------------------------------------------------------ 提交
    def submit_selected(self):
        ids = list(self.tree.selection())
        if not ids:
            messagebox.showinfo("提示", "先在任务表里选择要提交的任务")
            return
        n = self.manager.submit(ids)
        self.status_var.set(f"已提交 {n} 个任务")
        self.refresh()

    def submit_all(self):
        ids = [j.id for j in self.manager.list_jobs() if j.status == "staged"]
        n = self.manager.submit(ids)
        self.status_var.set(f"已提交 {n} 个任务")
        self.refresh()

    def cancel_selected(self):
        ids = list(self.tree.selection())
        if not ids:
            messagebox.showinfo("提示", "先选中任务")
            return
        for jid in ids:
            self.manager.cancel(jid)
        self.status_var.set(f"已请求中止 {len(ids)} 个")
        self.refresh()

    def remove_selected(self):
        for jid in list(self.tree.selection()):
            self.manager.remove(jid)
        self.selected = None
        self.refresh()

    def clear_finished(self):
        self.manager.clear_finished()
        self.refresh()

    def on_select(self, *_):
        sel = self.tree.selection()
        self.selected = sel[0] if sel else None
        self._log_sig = None
        self.show_log()

    # ------------------------------------------------------------------ 演示画图
    def plot_demo(self) -> None:
        """仅演示模式（M）：读取拉伸 CSV，一键画出应力-应变 / 载荷-位移。"""
        from ... import demo_plot

        job = self.manager.jobs.get(self.selected) if self.selected else None
        if job is None or job.machine != "M":
            cand = [j for j in self.manager.list_jobs() if j.machine == "M" and j.status == "done"]
            job = cand[0] if cand else None
        if job is None:
            messagebox.showinfo("一键画图（演示）", "请先在 M 演示模式提交并完成一个任务。", parent=self.root)
            return
        if job.status != "done":
            messagebox.showinfo("一键画图（演示）",
                                f"任务 {job.id} 还没完成（状态：{STATUS_TXT.get(job.status, job.status)}）。",
                                parent=self.root)
            return
        model = os.path.abspath(job.model)
        stem = os.path.splitext(os.path.basename(model))[0]
        folder = os.path.dirname(model)
        cands = sorted(Path(folder).glob(f"{stem}*_tensile.csv"))
        if not cands:
            messagebox.showwarning("一键画图（演示）",
                                   "没找到 *_tensile.csv。\n只有 M 演示模式（低碳钢拉伸）会生成该数据；"
                                   "复杂模型的探测 CSV 不在本功能范围内。",
                                   parent=self.root)
            return
        csv_path = cands[-1]
        summary = Path(str(csv_path).replace("_tensile.csv", "_summary.json"))
        try:
            demo_plot.show_tensile_plot(self.root, csv_path, summary if summary.exists() else None)
            self.status_var.set(f"已画出演示曲线：{csv_path.name}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("画图失败", str(exc), parent=self.root)

    # ------------------------------------------------------------------ 连接测试
    def probe(self):
        m = self.machine()
        backend = get_backend(m.backend, m.key)
        try:
            cmd = backend.build_probe_command()
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning("无法测试", str(exc))
            return
        self.status_var.set(f"正在测试 {m.label} …")

        def work():
            t0 = time.time()
            try:
                r = subprocess.run([find_bash(), "-lc", cmd], cwd=str(REPO),
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=60, creationflags=CREATE_NO_WINDOW)
                out = (r.stdout or "") + (r.stderr or "")
            except Exception as exc:  # noqa: BLE001
                out = f"[probe] 异常：{exc}"
            dt = time.time() - t0
            ok = "COMSOL_OK" in out and (m.key == "K" or "LINK_OK" in out)
            self.after(0, lambda: self._probe_done(m.label, dt, ok, out))

        threading.Thread(target=work, daemon=True).start()

    def _probe_done(self, label: str, dt: float, ok: bool, out: str):
        self.status_var.set(f"{label} 连接{'正常 ✓' if ok else '异常 ✗'}（{dt:.1f}s）")
        msg = "\n".join(l for l in out.strip().splitlines() if l.strip())[:600]
        messagebox.showinfo(f"{label} 测试结果", f"{'✅ 正常' if ok else '❌ 异常'}  {dt:.1f}s\n\n{msg}")

    # ------------------------------------------------------------------ 刷新
    def refresh(self):
        jobs = self.manager.list_jobs()
        seen = set()
        for j in jobs:
            seen.add(j.id)
            prog, stalled = self.manager.job_progress(j.id)
            if stalled:
                prog = (prog + " ⚠ 可能卡住").strip()
            vals = (j.id, MACHINES[j.machine].label, os.path.basename(j.model),
                    j.tag, j.cores, j.study or "全部",
                    "是" if j.save_solution else "",
                    STATUS_TXT.get(j.status, j.status),
                    (j.error[:70] if j.status == "failed" and j.error else ""),
                    prog if j.status == "running" else "",
                    f"{int(j.elapsed)} s" if j.elapsed else "")
            tags = ("stalled",) if stalled else (j.status,)
            if self.tree.exists(j.id):
                self.tree.item(j.id, values=vals, tags=tags)
            else:
                self.tree.insert("", "end", iid=j.id, values=vals, tags=tags)
        for iid in self.tree.get_children():
            if iid not in seen:
                self.tree.delete(iid)
        for k, m in MACHINES.items():
            busy = self.manager.machine_busy(k)
            staged = sum(1 for j in jobs if j.machine == k and j.status == "staged")
            pend = sum(1 for j in jobs if j.machine == k and j.status == "pending")
            lb = self.machine_labels[k]
            txt = f"{m.label}：" + (f"运行 {busy.id}（{int(busy.elapsed)} s）" if busy else "空闲")
            if pend:
                txt += f" · 排队 {pend}"
            if staged:
                txt += f" · 待提交 {staged}"
            lb.configure(text=txt, foreground="#a60" if busy else ("#8a6d00" if (pend or staged) else "#0a6"))
        self.after(700, self.refresh)

    # ------------------------------------------------------------------ 日志
    _KEEP_RE = re.compile(
        r"(\[(K|rext|ext|local|manager|GUI|probe|abort|M)\]"
        r"|Step\s+\d+\s*:\s*Time"
        r"|错误|失败|警告|不收敛|收敛|迭代|奇异|Error|Fail|Warning|Exception|Traceback"
        r"|研究 \d|第 \d+ 步|完成 ->|CSV|解模型已保存)", re.IGNORECASE)
    _STEP_ROW = re.compile(r"^\s{0,4}\d+\s+[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?\s+")

    def _filter_log(self, text: str) -> str:
        lines = text.splitlines()
        if self.full_log_var.get():
            return text
        kept = [l for l in lines if self._KEEP_RE.search(l)]
        steps = [l for l in lines if self._STEP_ROW.match(l)]
        tail = lines[-6:]
        out = list(kept[-300:])
        if steps:
            out += ["", "—— 最近时间步（看 Res 是否上升、NLfail 是否增加）——"] + steps[-12:]
        if kept or steps:
            out += ["", "... 完整内容请勾选上方“完整日志”"]
        out += ["", "—— 最近 6 行 ——"] + tail
        return chr(10).join(out)

    def toggle_log(self):
        self.log_collapsed = not self.log_collapsed
        if self.log_collapsed:
            self.log_body.grid_remove()
            self.log_toggle_btn.configure(text="展开日志 ▾")
        else:
            self.log_body.grid()
            self.log_toggle_btn.configure(text="收起日志 ▴")

    def pump_logs(self):
        self.show_log()
        self.after(600, self.pump_logs)

    def show_log(self):
        if not self.selected:
            return
        j = self.manager.jobs.get(self.selected)
        if not j:
            return
        path = self.manager.log_path(j.id)
        if not path.is_file():
            return
        try:
            st = path.stat()
        except OSError:
            return
        sig = (st.st_size, st.st_mtime, self.full_log_var.get())
        if sig == self._log_sig:
            return
        self._log_sig = sig
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        if len(text) > 120000:
            text = text[-120000:]
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", self._filter_log(text))
        self.log.see("end")
        self.log.configure(state="disabled")

    def on_app_close(self) -> bool:
        running = [j for j in self.manager.jobs.values() if j.status == "running"]
        if running and not messagebox.askyesno(
                "还有任务在运行", "有任务正在跑，退出会中止它们（远端可能仍在跑）。确定退出？"):
            return False
        for j in running:
            self.manager.cancel(j.id)
        return True
        self.root.destroy()

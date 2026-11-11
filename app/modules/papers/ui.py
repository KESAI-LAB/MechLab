"""文献 → 报告 模块：导入 PDF → 转 Markdown → 理论报告 + COMSOL 实现报告。

线程模型：耗时的转换/生成都在后台线程，通过 self.after 回主线程更新 UI。
"""
from __future__ import annotations

import os
import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..base import BaseModule
from . import report, settings, store
from .pdf2md import captions as pdf_captions
from .pdf2md import convert as pdf_convert
from .pdf2md import mineru_available

BACKEND_CHOICES = [
    ("PyMuPDF4LLM（快）", "pymupdf4llm"),
    ("MinerU（高质量，CPU 较慢）", "mineru"),
]
_BACKEND_BY_LABEL = {label: key for label, key in BACKEND_CHOICES}
_BACKEND_LABEL = {key: label for label, key in BACKEND_CHOICES}

STATUS_TXT = {
    "imported": "已导入",
    "converted": "已转 MD",
    "extracted": "已抽取",
    "done": "报告完成",
}
STATUS_COLOR = {
    "imported": "#6b7280",
    "converted": "#0a6",
    "extracted": "#a60",
    "done": "#0a6",
}


class PapersPage(BaseModule):
    title = "文献 → 报告"

    def __init__(self, master):
        super().__init__(master)
        self.papers: list[dict] = []
        self._busy = False
        self._uiq: "queue.Queue" = queue.Queue()
        self.status_var = tk.StringVar(value="就绪：导入 PDF 开始")
        pad = {"padx": 10, "pady": 6}

        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        ttk.Button(bar, text="＋ 导入 PDF…", command=self.import_pdfs).pack(side="left")
        ttk.Button(bar, text="① 转 Markdown", command=self.convert_selected).pack(side="left", padx=(12, 4))
        ttk.Button(bar, text="② 一键生成两份报告", command=self.generate_all).pack(side="left", padx=4)
        ttk.Button(bar, text="理论报告", command=self.generate_theory).pack(side="left", padx=(12, 4))
        ttk.Button(bar, text="COMSOL 实现报告", command=self.generate_impl).pack(side="left", padx=4)
        ttk.Button(bar, text="预览/打开", command=self.open_selected).pack(side="left", padx=(12, 4))
        ttk.Button(bar, text="打开文件夹", command=self.open_folder).pack(side="left", padx=4)
        ttk.Button(bar, text="导出 Markdown…", command=self.export_md).pack(side="left", padx=4)
        ttk.Button(bar, text="刷新", command=self.refresh).pack(side="left", padx=4)

        opt = ttk.Frame(self)
        opt.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(opt, text="PDF 后端").pack(side="left")
        key = settings.get("pdf_backend", "pymupdf4llm")
        self.backend_var = tk.StringVar(value=_BACKEND_LABEL.get(key, BACKEND_CHOICES[0][0]))
        self.backend_cb = ttk.Combobox(opt, textvariable=self.backend_var,
                                       values=[label for label, _ in BACKEND_CHOICES],
                                       state="readonly", width=24)
        self.backend_cb.pack(side="left", padx=6)
        self.backend_cb.bind("<<ComboboxSelected>>", self._on_backend_change)
        self.mineru_label = ttk.Label(opt, text="", foreground="#6b7280")
        self.mineru_label.pack(side="left", padx=10)
        self._update_backend_hint()

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, **pad)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        cols = ("title", "status", "chars", "pages", "theory", "impl")
        heads = {"title": "标题", "status": "状态", "chars": "字符", "pages": "页数",
                 "theory": "理论报告", "impl": "实现报告"}
        widths = {"title": 460, "status": 90, "chars": 80, "pages": 60, "theory": 90, "impl": 90}
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor="w")
        ys = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", lambda *_: self._update_status())
        self.tree.bind("<Double-1>", lambda *_: self.open_selected())

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", **pad)
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=180)
        self.progress.pack(side="left")
        ttk.Label(bottom, textvariable=self.status_var, foreground="#4b5563").pack(
            side="left", padx=10, fill="x", expand=True)

        ttk.Label(self, text="提示：报告为 Markdown（含 LaTeX），可直接放进 Obsidian vault；"
                             "首次使用 DeepSeek 网页需登录一次（浏览器会弹出）。",
                  foreground="#6b7280").pack(fill="x", padx=10, pady=(0, 6))
        self.refresh()
        self.after(80, self._pump_ui)

    # ------------------------------------------------------------------ UI 线程队列
    def _post(self, fn) -> None:
        self._uiq.put(fn)

    def _pump_ui(self) -> None:
        try:
            while True:
                fn = self._uiq.get_nowait()
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass
        except queue.Empty:
            pass
        try:
            self.after(80, self._pump_ui)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 列表
    def refresh(self) -> None:
        keep = self.tree.selection()
        keep_id = keep[0] if keep else None
        self.papers = store.list_papers()
        self.tree.delete(*self.tree.get_children())
        for p in self.papers:
            d = store.paper_dir(p["id"])
            theory = "✓" if (d / "theory.md").is_file() else ""
            impl = "✓" if (d / "implementation.md").is_file() else ""
            self.tree.insert("", "end", iid=p["id"], values=(
                p["title"][:70],
                STATUS_TXT.get(p["status"], p["status"]),
                p["chars"] or "",
                p["pages"] or "",
                theory, impl,
            ))
        if keep_id and self.tree.exists(keep_id):
            self.tree.selection_set(keep_id)
        self._update_backend_hint()
        self._update_status()

    def selected_paper(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            return None
        pid = sel[0]
        for p in self.papers:
            if p["id"] == pid:
                return p
        return None

    def _update_status(self) -> None:
        p = self.selected_paper()
        if not p:
            self.status_var.set(f"共 {len(self.papers)} 篇文献；选中一行开始处理")
            return
        d = store.paper_dir(p["id"])
        bits = [f"{p['title'][:40]}", STATUS_TXT.get(p["status"], p["status"])]
        if p.get("warning"):
            bits.append(f"⚠ {p['warning']}")
        if (d / "extraction.json").is_file():
            bits.append("已抽取")
        self.status_var.set("  ·  ".join(bits))

    # ------------------------------------------------------------------ 忙状态
    def _set_busy(self, busy: bool, msg: str = "") -> None:
        self._busy = busy
        if busy:
            self.progress.start(12)
            self.status_var.set(msg)
        else:
            self.progress.stop()

    def _error(self, title: str, exc: Exception) -> None:
        self._set_busy(False)
        messagebox.showerror(title, str(exc), parent=self)

    def _bg(self, work, ok) -> None:
        def runner():
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001
                self._post(lambda e=exc: self._error("处理失败", e))
                return
            self._post(lambda: ok(result))

        threading.Thread(target=runner, daemon=True).start()

    def _progress(self, msg: str) -> None:
        self._post(lambda: self.status_var.set(msg))

    # ------------------------------------------------------------------ 导入
    def import_pdfs(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self, title="选择 PDF 文献", filetypes=[("PDF", "*.pdf"), ("所有文件", "*.*")])
        if not paths:
            return
        added = 0
        for path in paths:
            try:
                store.add_paper(path)
                added += 1
            except Exception as exc:  # noqa: BLE001
                messagebox.showwarning("导入失败", f"{Path(path).name}\n{exc}", parent=self)
        self.refresh()
        self.status_var.set(f"已导入 {added} 篇；选中后点「① 转 Markdown」")

    # ------------------------------------------------------------------ 转换
    # ------------------------------------------------------------------ 后端选择
    def _backend_key(self) -> str:
        return _BACKEND_BY_LABEL.get(self.backend_var.get(), "pymupdf4llm")

    def _on_backend_change(self, *_) -> None:
        settings.set_value("pdf_backend", self._backend_key())
        self._update_backend_hint()

    def _update_backend_hint(self) -> None:
        if mineru_available():
            self.mineru_label.config(text="MinerU：已检测到 ✓", foreground="#0a6")
        else:
            self.mineru_label.config(
                text='MinerU：未安装（pip install -U "mineru[core]"）', foreground="#b45309")

    # ------------------------------------------------------------------ 转换
    def convert_selected(self) -> None:
        p = self.selected_paper()
        if not p:
            messagebox.showinfo("提示", "先在列表里选中一篇文献", parent=self)
            return
        if self._busy:
            return
        backend = self._backend_key()
        settings.set_value("pdf_backend", backend)
        label = _BACKEND_LABEL.get(backend, backend)
        self._set_busy(True, f"正在转换（{label}）：{p['title'][:40]} …")

        def work():
            res = pdf_convert(backend, p["pdf_path"], store.paper_dir(p["id"]))
            md_text = Path(res["md_path"]).read_text(encoding="utf-8")
            figs = pdf_captions.write_figures_md(md_text, store.paper_dir(p["id"]))
            fig_map = pdf_captions.build_figure_map(store.paper_dir(p["id"]), md_text)
            res["captions"] = figs["count"]
            res["figures"] = len(fig_map.get("figures") or [])
            res["figure_source"] = fig_map.get("source", "none")
            warning = res.get("warning") or ""
            store.update_paper(p["id"], md_path=res["md_path"], chars=res["chars"],
                               headings=res["headings"], images=res["images"],
                               status="converted", warning=warning)
            return res

        def ok(res):
            self._set_busy(False)
            self.refresh()
            self.status_var.set(
                f"转换完成（{_BACKEND_LABEL.get(res.get('backend', ''), res.get('backend', ''))}）："
                f"{res['chars']} 字符 / {res['images']} 图 / 图注 {res.get('captions', 0)} 条 / "
                f"可插图标 {res.get('figures', 0)} 张 / {res['elapsed']}s"
                + (f"  ⚠ {res['warning']}" if res["warning"] else ""))

        self._bg(work, ok)

    # ------------------------------------------------------------------ 报告
    def _ensure_md(self, p: dict) -> None:
        if not p.get("md_path") or not Path(p["md_path"]).is_file():
            raise RuntimeError("还没有 paper.md，请先点「① 转 Markdown」")

    def generate_all(self) -> None:
        p = self.selected_paper()
        if not p or self._busy:
            if not p:
                messagebox.showinfo("提示", "先在列表里选中一篇文献", parent=self)
            return
        try:
            self._ensure_md(p)
        except RuntimeError as exc:
            messagebox.showwarning("提示", str(exc), parent=self)
            return
        self._set_busy(True, "正在生成报告（抽取 → 理论 → 实现，约 3–6 分钟）…")
        self.status_var.set("生成中：若弹出 DeepSeek 登录页，请在浏览器里登录（最多等 15 分钟）…")

        def work():
            return report.run_all(p["id"], progress=self._progress, login_timeout=900)

        def ok(res):
            self._set_busy(False)
            self.refresh()
            self.status_var.set("两份报告已生成：double-click 或点「预览/打开」")
            messagebox.showinfo("完成", "理论报告 + COMSOL 实现报告已生成。", parent=self)

        self._bg(work, ok)

    def generate_theory(self) -> None:
        self._one_report("theory")

    def generate_impl(self) -> None:
        self._one_report("implementation")

    def _one_report(self, kind: str) -> None:
        p = self.selected_paper()
        if not p or self._busy:
            if not p:
                messagebox.showinfo("提示", "先在列表里选中一篇文献", parent=self)
            return
        try:
            self._ensure_md(p)
        except RuntimeError as exc:
            messagebox.showwarning("提示", str(exc), parent=self)
            return
        self._set_busy(True, f"正在生成{'理论报告' if kind == 'theory' else 'COMSOL 实现报告'}…")

        def work():
            data = None
            if (store.paper_dir(p["id"]) / "extraction.json").is_file():
                import json
                data = json.loads((store.paper_dir(p["id"]) / "extraction.json").read_text(encoding="utf-8"))
            if kind == "theory":
                return report.write_theory(p["id"], data, progress=self._progress, login_timeout=900)
            return report.write_implementation(p["id"], data, progress=self._progress, login_timeout=900)

        def ok(path):
            self._set_busy(False)
            self.refresh()
            self.status_var.set(f"已生成：{path}")
            os.startfile(str(path))

        self._bg(work, ok)

    # ------------------------------------------------------------------ 打开
    def open_selected(self) -> None:
        p = self.selected_paper()
        if not p:
            messagebox.showinfo("提示", "先选中一篇文献", parent=self)
            return
        d = store.paper_dir(p["id"])
        for name in ("theory.md", "implementation.md", "paper.md"):
            f = d / name
            if f.is_file():
                os.startfile(str(f))
                return
        self.open_folder()

    def open_folder(self) -> None:
        p = self.selected_paper()
        if not p:
            path = store.DATA_ROOT
        else:
            path = store.paper_dir(p["id"])
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def export_md(self) -> None:
        """把报告 Markdown 复制到指定目录（可直接选 Obsidian vault 里的文件夹）。"""
        p = self.selected_paper()
        if not p:
            messagebox.showinfo("提示", "先选中一篇文献", parent=self)
            return
        d = store.paper_dir(p["id"])
        files = [d / n for n in ("theory.md", "implementation.md", "paper.md") if (d / n).is_file()]
        if not files:
            messagebox.showwarning("没有可导出的文件", "先生成 Markdown 或报告", parent=self)
            return
        out = filedialog.askdirectory(parent=self, title="选择导出目录（可指向 Obsidian vault）")
        if not out:
            return
        safe = "".join(ch for ch in p["title"][:40] if ch not in '\\/:*?"<>|').strip() or p["id"]
        target = Path(out) / safe
        target.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(f, target / f.name)
        # 报告里的图片用相对路径 assets/...，导出时一起复制
        assets = d / "assets"
        if assets.is_dir():
            shutil.copytree(assets, target / "assets", dirs_exist_ok=True)
        for extra in ("figures.json", "figures.md"):
            if (d / extra).is_file():
                shutil.copy2(d / extra, target / extra)
        self.status_var.set(f"已导出 {len(files)} 个 Markdown + assets 到 {target}")
        messagebox.showinfo("导出完成", f"已导出到：\n{target}", parent=self)

    # ------------------------------------------------------------------ 关闭
    def on_app_close(self) -> bool:
        return True

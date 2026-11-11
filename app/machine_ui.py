"""接入新机向导页：生成采集脚本 → 在新机运行 → 粘贴输出自动识别 → 填参 → 测试连接 → 保存。"""
from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import machine_probe
from . import machines as machines_mod
from .config import REPO
from .runner import CREATE_NO_WINDOW, find_bash


def open_machine_setup(app) -> None:
    MachineSetupPage(app)


class MachineSetupPage(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("接入新机")
        self.geometry("960x880")
        self.minsize(880, 760)
        self.transient(app.root)
        self.resizable(True, True)

        pad = {"padx": 10, "pady": 6}
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, **pad)

        ttk.Label(
            root,
            text="把下面这段 PowerShell 脚本复制到新机器上运行，再把输出粘贴回来，程序会自动识别主机、COMSOL、核数等信息。\n"
                 "若新机还没开 SSH：先点「新机没开 SSH？生成启动脚本…」，用管理员 PowerShell 运行，再回来做第 1、2 步。",
            foreground="#333", wraplength=900, justify="left",
        ).pack(fill="x", pady=(0, 6))

        # ---------------- 第 1 步：采集脚本 ----------------
        step1 = ttk.LabelFrame(root, text="第 1 步：在新机器上运行采集脚本（Windows PowerShell）")
        step1.pack(fill="both", expand=False, pady=(0, 6))

        bar1 = ttk.Frame(step1)
        bar1.pack(fill="x", padx=6, pady=4)
        ttk.Button(bar1, text="生成采集脚本", command=self._fill_script).pack(side="left")
        ttk.Button(bar1, text="复制脚本到剪贴板", command=self._copy_script).pack(side="left", padx=6)
        ttk.Button(bar1, text="新机没开 SSH？生成启动脚本…",
                   command=lambda: SshEnableDialog(self)).pack(side="left", padx=6)
        self.script_path_hint = ttk.Label(bar1, text="", foreground="#666")
        self.script_path_hint.pack(side="left", padx=8)

        box1 = ttk.Frame(step1)
        box1.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.script_text = tk.Text(box1, height=10, wrap="none", font=("Consolas", 9))
        sb1 = ttk.Scrollbar(box1, orient="vertical", command=self.script_text.yview)
        self.script_text.configure(yscrollcommand=sb1.set)
        self.script_text.pack(side="left", fill="both", expand=True)
        sb1.pack(side="right", fill="y")

        # ---------------- 第 2 步：粘贴输出 ----------------
        step2 = ttk.LabelFrame(root, text="第 2 步：把新机器上的输出粘贴到下面，点“解析并填入”")
        step2.pack(fill="both", expand=True, pady=(0, 6))

        bar2 = ttk.Frame(step2)
        bar2.pack(fill="x", padx=6, pady=4)
        ttk.Button(bar2, text="解析并自动填入", command=self._parse).pack(side="left")
        ttk.Button(bar2, text="清空粘贴区", command=lambda: self.paste_text.delete("1.0", "end")).pack(side="left", padx=6)
        self.parse_status = ttk.Label(bar2, text="", foreground="#666")
        self.parse_status.pack(side="left", padx=8)

        box2 = ttk.Frame(step2)
        box2.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.paste_text = tk.Text(box2, height=8, wrap="word", font=("Consolas", 9))
        sb2 = ttk.Scrollbar(box2, orient="vertical", command=self.paste_text.yview)
        self.paste_text.configure(yscrollcommand=sb2.set)
        self.paste_text.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")

        # ---------------- 第 3 步：确认参数 ----------------
        step3 = ttk.LabelFrame(root, text="第 3 步：确认连接参数")
        step3.pack(fill="x", pady=(0, 6))

        self.vars: dict[str, tk.StringVar] = {}
        rows = [
            ("label", "显示名", 24),
            ("host", "主机 user@host", 32),
            ("port", "SSH 端口", 8),
            ("key_path", "私钥路径", 52),
            ("base_win", "远程工作目录（Win）", 40),
            ("base_unix", "远程工作目录（Unix）", 40),
            ("batch", "comsolbatch 路径", 60),
            ("compile", "comsolcompile 路径", 60),
            ("cores", "核数", 8),
        ]
        for i, (key, label, width) in enumerate(rows):
            col = i % 2
            row = i // 2
            cell = ttk.Frame(step3)
            cell.grid(row=row, column=col, sticky="we", padx=6, pady=3)
            ttk.Label(cell, text=label, width=20, anchor="e").pack(side="left")
            var = tk.StringVar()
            self.vars[key] = var
            ttk.Entry(cell, textvariable=var, width=width).pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.boundary_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(step3, text="支持 @b 边界探针", variable=self.boundary_var).grid(
            row=5, column=0, sticky="w", padx=6, pady=3)

        btns = ttk.Frame(step3)
        btns.grid(row=5, column=1, sticky="we", padx=6, pady=3)
        ttk.Button(btns, text="选择私钥…", command=self._pick_key).pack(side="left")
        self.test_btn = ttk.Button(btns, text="测试连接", command=self._test)
        self.test_btn.pack(side="left", padx=6)
        self.test_status = ttk.Label(btns, text="", foreground="#666", wraplength=420)
        self.test_status.pack(side="left", padx=6)

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", pady=(4, 0))
        ttk.Button(bottom, text="保存并启用", command=self._save).pack(side="right")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right", padx=8)
        ttk.Label(bottom, text="私钥只保存在本机 machines.json（已被 .gitignore 排除）",
                  foreground="#888").pack(side="left")

        self._fill_script()

    # ------------------------------------------------------------------ 第 1 步
    def _fill_script(self) -> None:
        self.script_text.delete("1.0", "end")
        self.script_text.insert("1.0", machine_probe.PROBE_SCRIPT)

    def _copy_script(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(machine_probe.PROBE_SCRIPT)
        self.script_path_hint.config(text="已复制到剪贴板 ✓")
        self.after(2500, lambda: self.script_path_hint.config(text=""))

    # ------------------------------------------------------------------ 第 2 步
    def _parse(self) -> None:
        text = self.paste_text.get("1.0", "end")
        try:
            data = machine_probe.parse_probe_text(text)
        except ValueError as exc:
            self.parse_status.config(text=f"解析失败：{exc}", foreground="#c33")
            return
        summary = machine_probe.summary_lines(data)
        self.parse_status.config(text="解析成功", foreground="#0a6")
        messagebox.showinfo("采集结果", "\n".join(summary), parent=self)
        sug = machine_probe.suggest_config(data)
        for key, value in sug.items():
            if key in self.vars:
                self.vars[key].set(str(value))
        # 私钥留空给用户选
        self.parse_status.config(text="已自动填入表单（私钥请手动选择）", foreground="#0a6")

    def _pick_key(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="选择 SSH 私钥")
        if path:
            self.vars["key_path"].set(path)

    # ------------------------------------------------------------------ 测试
    def _form(self) -> machines_mod.CustomMachine:
        return machines_mod.CustomMachine(
            label=self.vars["label"].get().strip(),
            host=self.vars["host"].get().strip(),
            port=int(self.vars["port"].get() or 22),
            key_path=self.vars["key_path"].get().strip(),
            base_win=self.vars["base_win"].get().strip(),
            base_unix=self.vars["base_unix"].get().strip(),
            batch=self.vars["batch"].get().strip(),
            compile=self.vars["compile"].get().strip(),
            cores=int(self.vars["cores"].get() or 8),
            supports_boundary=self.boundary_var.get(),
        )

    def _test(self) -> None:
        try:
            cm = self._form()
            if "@" not in cm.host:
                raise ValueError("主机要写成 user@host")
            if not cm.key_path:
                raise ValueError("请先选择私钥")
        except ValueError as exc:
            self.test_status.config(text=str(exc), foreground="#c33")
            return

        self.test_btn.config(state="disabled")
        self.test_status.config(text="连接中…", foreground="#666")
        cmd = (
            f'ssh -i {_q(cm.key_path)} -p {cm.port} -o BatchMode=yes '
            f'-o StrictHostKeyChecking=no -o ConnectTimeout=10 {_q(cm.host)} '
            f'"echo LINK_OK && if exist \\"{cm.batch}\\" (echo COMSOL_OK) else (echo COMSOL_MISSING)" 2>&1'
        )
        threading.Thread(target=self._run_test, args=(cmd,), daemon=True).start()

    def _run_test(self, cmd: str) -> None:
        try:
            proc = subprocess.run([find_bash(), "-lc", cmd], cwd=str(REPO),
                                  capture_output=True, text=True, timeout=40,
                                  creationflags=CREATE_NO_WINDOW)
            out = (proc.stdout or "") + (proc.stderr or "")
        except Exception as exc:  # noqa: BLE001
            out = f"启动失败：{exc}"
        self.after(0, lambda: self._finish_test(out))

    def _finish_test(self, out: str) -> None:
        self.test_btn.config(state="normal")
        text = out.strip().splitlines()[-6:]
        self.test_status.config(text="\n".join(text), foreground="#0a6" if "LINK_OK" in out else "#c33")

    # ------------------------------------------------------------------ 保存
    def _save(self) -> None:
        try:
            cm = self._form()
            cm.validate()
        except ValueError as exc:
            messagebox.showwarning("参数不完整", str(exc), parent=self)
            return
        try:
            m = machines_mod.save_machine(cm)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        try:
            self.app.manager.register_machine(m.key)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.app.refresh_machines()
        except Exception:  # noqa: BLE001
            pass
        messagebox.showinfo("已添加", f"机器「{m.label}」已加入列表。\n先在界面点「测试连接」确认可用。", parent=self)
        self.destroy()


class SshEnableDialog(tk.Toplevel):
    """新机没开 SSH 时：生成"安装/启动 OpenSSH Server + 写入公钥"的管理员脚本。"""

    def __init__(self, parent_page):
        super().__init__(parent_page)
        self.title("生成 SSH 启动脚本（新机未开 SSH 时使用）")
        self.geometry("840x660")
        self.minsize(720, 520)
        self.transient(parent_page)
        pad = {"padx": 10, "pady": 6}
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, **pad)

        ttk.Label(
            root,
            text="在新机上用【管理员 PowerShell】运行：右键 PowerShell → 以管理员身份运行 → 粘贴脚本 → 回车。\n"
                 "脚本会：检查/安装 OpenSSH Server → 启动 sshd → 放行 22 端口 → 写入公钥 → 打印 SSH_READY。\n"
                 "（安装 OpenSSH 需要联网/Windows Update；若离线，先手动装好再运行脚本）",
            wraplength=780, justify="left", foreground="#333",
        ).pack(fill="x")

        row = ttk.Frame(root)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="公钥（可选）").pack(side="left")
        self.pub_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.pub_var, width=64).pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(row, text="从私钥文件读取 .pub", command=self._load_pub).pack(side="left")

        bar = ttk.Frame(root)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="生成脚本", command=self._generate).pack(side="left")
        ttk.Button(bar, text="复制到剪贴板", command=self._copy).pack(side="left", padx=6)
        self.hint = ttk.Label(bar, text="", foreground="#0a6")
        self.hint.pack(side="left", padx=8)

        box = ttk.Frame(root)
        box.pack(fill="both", expand=True, pady=4)
        self.text = tk.Text(box, wrap="none", font=("Consolas", 9))
        sb = ttk.Scrollbar(box, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        ttk.Button(root, text="关闭", command=self.destroy).pack(side="right", pady=(4, 0))
        self._generate()

    def _generate(self) -> None:
        script = machine_probe.build_ssh_enable_script(self.pub_var.get())
        self.text.delete("1.0", "end")
        self.text.insert("1.0", script)

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.text.get("1.0", "end").rstrip())
        self.hint.config(text="已复制 ✓")
        self.after(2000, lambda: self.hint.config(text=""))

    def _load_pub(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="选择公钥（.pub）或私钥（自动找同名 .pub）")
        if not path:
            return
        p = Path(path)
        if p.suffix != ".pub":
            cand = Path(str(p) + ".pub")
            if cand.is_file():
                p = cand
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("读取失败", str(exc), parent=self)
            return
        key = ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(("ssh-rsa", "ssh-ed25519", "ecdsa-", "sk-")):
                key = line
                break
        if not key:
            messagebox.showwarning("没找到公钥", "文件里没有 ssh-rsa / ssh-ed25519 开头的内容", parent=self)
            return
        self.pub_var.set(key)
        self._generate()
        self.hint.config(text=f"已读取 {p.name}")


def _q(s: str) -> str:
    import shlex
    return shlex.quote(s)

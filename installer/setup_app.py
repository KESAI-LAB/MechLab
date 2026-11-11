"""MechLab 安装器（PyInstaller onefile，内置 MechLab.zip）。

安装到 %LOCALAPPDATA%\\Programs\\MechLab，创建桌面/开始菜单快捷方式并启动。
"""
from __future__ import annotations

import os
import subprocess
import sys
import traceback
import zipfile
from pathlib import Path

import tkinter as tk
from tkinter import ttk

APP_NAME = "MechLab"
VERSION = "2.0-dev"
CREATE_NO_WINDOW = 0x08000000


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def install_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / APP_NAME


class SetupApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"{APP_NAME} {VERSION} 安装程序")
        root.geometry("560x320")
        root.resizable(False, False)
        root.configure(bg="#111827")

        header = tk.Frame(root, bg="#111827", height=88)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text=APP_NAME, bg="#111827", fg="#FFFFFF",
                 font=("Microsoft YaHei UI", 20, "bold")).pack(side="left", padx=18, pady=(14, 0))
        tk.Label(header, text=f"v{VERSION} · COMSOL 提交 / 文献报告", bg="#111827",
                 fg="#9CA3AF", font=("Microsoft YaHei UI", 9)).place(x=20, y=52)
        tk.Label(header, text="KESAI", bg="#111827", fg="#4B5563",
                 font=("Segoe UI", 9)).pack(side="right", padx=16, pady=20)

        body = tk.Frame(root, bg="#111827")
        body.pack(fill="both", expand=True, padx=22, pady=10)
        self.status = tk.StringVar(value="准备安装…")
        tk.Label(body, textvariable=self.status, bg="#111827", fg="#D1D5DB",
                 font=("Microsoft YaHei UI", 10), anchor="w").pack(fill="x", pady=(6, 8))
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:  # noqa: BLE001
            pass
        style.configure("Install.Horizontal.TProgressbar", troughcolor="#1F2937",
                        background="#2F6FED", bordercolor="#1F2937", lightcolor="#2F6FED",
                        darkcolor="#2F6FED")
        self.progress = ttk.Progressbar(body, style="Install.Horizontal.TProgressbar",
                                        mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 14))
        self.detail = tk.StringVar(value=f"安装目录：{install_dir()}")
        tk.Label(body, textvariable=self.detail, bg="#111827", fg="#6B7280",
                 font=("Microsoft YaHei UI", 8), anchor="w").pack(fill="x")

        self.root.after(250, self.install)

    # ------------------------------------------------------------------
    def set_status(self, text: str, pct: float | None = None) -> None:
        self.status.set(text)
        if pct is not None:
            self.progress["value"] = max(0.0, min(100.0, pct))
        self.root.update_idletasks()

    def install(self) -> None:
        try:
            zip_path = base_dir() / "MechLab.zip"
            if not zip_path.is_file():
                raise FileNotFoundError(f"安装包内缺少 MechLab.zip：{zip_path}")
            target = install_dir()
            target.mkdir(parents=True, exist_ok=True)
            self.set_status("正在解压文件（约 1–2 分钟）…", 0)
            with zipfile.ZipFile(zip_path) as zf:
                names = [n for n in zf.namelist() if n and not n.endswith("/")]
                total = len(names)
                for i, name in enumerate(names, 1):
                    zf.extract(name, target)
                    if i % max(1, total // 100) == 0 or i == total:
                        self.set_status(f"正在解压文件（{i}/{total}）…", i * 100 / total)

            self.set_status("正在创建快捷方式…", 100)
            self.create_shortcuts()

            exe = target / "MechLab.exe"
            self.set_status("安装完成，正在启动 MechLab…", 100)
            subprocess.Popen([str(exe)], cwd=str(target), creationflags=CREATE_NO_WINDOW)
            self.root.after(1200, self.root.destroy)
        except Exception as exc:  # noqa: BLE001
            log = Path(os.environ.get("LOCALAPPDATA", ".")) / "MechLab-install-error.log"
            try:
                log.write_text(traceback.format_exc(), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            self.status.set(f"安装失败：{exc}")
            tk.Label(self.root, text=f"失败日志：{log}", bg="#111827", fg="#F87171",
                     font=("Microsoft YaHei UI", 8)).pack(side="bottom", pady=6)
            self.root.after(6000, self.root.destroy)

    def create_shortcuts(self) -> None:
        exe = install_dir() / "MechLab.exe"
        script = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$exe = '{exe}'; $wd = '{install_dir()}'; "
            "$desk = [Environment]::GetFolderPath('Desktop'); "
            "$s = $ws.CreateShortcut((Join-Path $desk 'MechLab.lnk')); "
            "$s.TargetPath = $exe; $s.WorkingDirectory = $wd; $s.IconLocation = \"$exe,0\"; "
            "$s.Description = 'MechLab v2.0-dev'; $s.Save(); "
            "$sm = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'; "
            "$s2 = $ws.CreateShortcut((Join-Path $sm 'MechLab.lnk')); "
            "$s2.TargetPath = $exe; $s2.WorkingDirectory = $wd; $s2.IconLocation = \"$exe,0\"; $s2.Save()"
        )
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-Command", script], check=True, creationflags=CREATE_NO_WINDOW)


def main() -> None:
    root = tk.Tk()
    SetupApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

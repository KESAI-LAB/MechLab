"""构建 MechLab 安装包（PyInstaller onefile 安装器，无需 Inno/NSIS）。

流程：
  1. 把 engine/ examples/ docs/ 等复制到 dist/MechLab（PyInstaller onedir 产物旁边）；
  2. 打包 staging/MechLab.zip；
  3. 用 PyInstaller 把 installer/setup_app.py + MechLab.zip 打成
     dist/MechLab-Setup-<version>.exe（单文件安装器）；
  4. 同时输出 dist/MechLab-Portable-<version>.zip 便携版。

用法：
  python scripts/build_installer.py
前置：
  - 已用 PyInstaller 生成 dist/MechLab/MechLab.exe
  - pip install pyinstaller
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "MechLab"
# onefile 安装器在含空格路径下可能解不出临时目录，staging 放无空格路径
STAGING = Path(r"C:\MechLabSetup")
VERSION = "2.0-dev"
SETUP_NAME = f"MechLab-Setup-{VERSION}"
PORTABLE_NAME = f"MechLab-Portable-{VERSION}.zip"

FOLDERS = ("engine", "examples", "docs")
EXTRA_FILES = ("README.md", "requirements.txt")


def copy_runtime_files() -> None:
    for name in FOLDERS:
        src = ROOT / name
        dst = DIST / name
        if not src.is_dir():
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.log"))
    for name in EXTRA_FILES:
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, DIST / name)


def make_zip() -> Path:
    STAGING.mkdir(parents=True, exist_ok=True)
    zip_path = STAGING / "MechLab.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(DIST.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(DIST).as_posix())
    return zip_path


def build_setup(zip_path: Path) -> Path:
    out = ROOT / "dist_installer"
    work = ROOT / "build_installer"
    exe = out / f"{SETUP_NAME}.exe"
    if exe.exists():
        exe.unlink()
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", SETUP_NAME,
        "--icon", str(ROOT / "app" / "assets" / "mechlab.ico"),
        "--add-data", f"{zip_path};.",
        "--distpath", str(out),
        "--workpath", str(work),
        str(ROOT / "installer" / "setup_app.py"),
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)
    final = ROOT / "dist" / f"{SETUP_NAME}.exe"
    shutil.copy2(exe, final)
    return final


def main() -> int:
    if not (DIST / "MechLab.exe").is_file():
        print("缺少 dist/MechLab/MechLab.exe，请先运行 PyInstaller 构建应用", file=sys.stderr)
        return 1

    print("[1/3] 复制 engine/examples/docs …")
    copy_runtime_files()

    print("[2/3] 压缩 MechLab.zip …")
    zip_path = make_zip()
    print(f"      {zip_path}  {zip_path.stat().st_size / 1024 / 1024:.1f} MB")
    portable = ROOT / "dist" / PORTABLE_NAME
    shutil.copy2(zip_path, portable)
    print(f"      便携版：{portable}")

    print("[3/3] 构建安装器（PyInstaller onefile）…")
    setup = build_setup(zip_path)
    print(f"完成：{setup}  {setup.stat().st_size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

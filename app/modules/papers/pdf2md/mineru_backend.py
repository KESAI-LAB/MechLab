"""MinerU 后端：外部 CLI 调用（高质量公式/表格/图片提取）。

前置：
    pip install -U "mineru[core]"
    （首次运行会自动下载模型；国内可设 MINERU_MODEL_SOURCE=modelscope）

可用环境变量：
    MINERU_CMD         自定义命令（默认自动找 mineru / magic-pdf）
    MINERU_DEVICE      cpu / cuda（默认 cpu）
    MINERU_TIMEOUT     超时秒数（默认 1800）
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from ....config import PROJECT_ROOT

IMG_SUFFIX = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def find_command() -> list[str] | None:
    env = os.environ.get("MINERU_CMD", "").strip()
    if env:
        return env.split()
    # 优先项目内专用 venv（避免污染主环境）
    for rel in (".venvs/mineru/Scripts/mineru.exe", ".venvs/mineru/bin/mineru"):
        p = PROJECT_ROOT / rel
        if p.is_file():
            return [str(p)]
    for name in ("mineru", "magic-pdf"):
        path = shutil.which(name)
        if path:
            return [path]
    return None


def available() -> bool:
    return find_command() is not None


def version_hint() -> str:
    cmd = find_command()
    return " ".join(cmd) if cmd else "未安装（pip install -U \"mineru[core]\"）"


def _build_args(cmd: list[str], pdf: Path, out: Path, device: str,
                start_page: int | None = None, end_page: int | None = None,
                method: str | None = None) -> list[str]:
    name = Path(cmd[0]).name.lower()
    if name.startswith("magic-pdf"):
        return cmd + ["-p", str(pdf), "-o", str(out), "-m", "auto"]
    # MinerU 2.x/4.x 新 CLI
    args = cmd + ["-p", str(pdf), "-o", str(out), "-b", "pipeline", "-d", device]
    if method:
        args += ["-m", method]
    if start_page is not None:
        args += ["-s", str(start_page)]
    if end_page is not None:
        args += ["-e", str(end_page)]
    return args


def _rewrite_links(text: str, assets: Path) -> str:
    """把 MinerU 输出的相对路径（images/xxx.jpg、../images/xxx.jpg）改成 assets/xxx。"""
    def repl(m: re.Match) -> str:
        alt, path = m.group(1), m.group(2)
        return f"![{alt}](assets/{Path(path).name})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl, text)


def convert(pdf_path: str | Path, out_dir: str | Path, device: str | None = None,
            timeout: int | None = None, start_page: int | None = None,
            end_page: int | None = None, method: str | None = None, **_: object) -> dict:
    cmd = find_command()
    if not cmd:
        raise RuntimeError(
            "未检测到 MinerU。请先安装：\n"
            "  python -m venv .venvs/mineru\n"
            "  .venvs/mineru/Scripts/python -m pip install -U \"mineru[core]\"\n"
            "并在设置里选择 MinerU 后端；首次运行需下载模型（可设 MINERU_MODEL_SOURCE=modelscope）。")

    pdf = Path(pdf_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "mineru_raw"
    if raw.exists():
        shutil.rmtree(raw, ignore_errors=True)
    raw.mkdir(parents=True, exist_ok=True)

    device = device or os.environ.get("MINERU_DEVICE", "cpu")
    timeout = timeout or int(os.environ.get("MINERU_TIMEOUT", "1800"))
    args = _build_args(cmd, pdf, raw, device, start_page, end_page, method)

    env = os.environ.copy()
    env.setdefault("MINERU_MODEL_SOURCE", "modelscope")
    project_cache = PROJECT_ROOT / ".venvs" / "modelscope"
    if project_cache.is_dir():
        env.setdefault("MODELSCOPE_CACHE", str(project_cache))
    project_cfg = PROJECT_ROOT / ".venvs" / "mineru" / "mineru.json"
    if project_cfg.is_file():
        env.setdefault("MINERU_TOOLS_CONFIG_JSON", str(project_cfg))
    # 把各库的缓存/配置目录都限制在项目内（避免写 C 盘用户目录失败）
    runtime = PROJECT_ROOT / ".venvs" / "mineru"
    env.setdefault("YOLO_CONFIG_DIR", str(runtime / "ultralytics"))
    env.setdefault("MPLCONFIGDIR", str(runtime / "mpl"))
    env.setdefault("TORCH_HOME", str(runtime / "torch"))
    env.setdefault("HF_HOME", str(runtime / "hf"))
    t0 = time.time()
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env)
    elapsed = time.time() - t0
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        raise RuntimeError(f"MinerU 运行失败（exit {proc.returncode}）：\n{tail}")

    mds = sorted(raw.rglob("*.md"), key=lambda p: p.stat().st_size, reverse=True)
    if not mds:
        raise RuntimeError(f"MinerU 没有产出 Markdown（输出目录：{raw}）")
    md_src = mds[0]
    text = md_src.read_text(encoding="utf-8", errors="replace")

    assets = out / "assets"
    assets.mkdir(exist_ok=True)
    n_images = 0
    for img in raw.rglob("*"):
        if img.is_file() and img.suffix.lower() in IMG_SUFFIX:
            try:
                shutil.copy2(img, assets / img.name)
                n_images += 1
            except Exception:  # noqa: BLE001
                pass
    text = _rewrite_links(text, assets)

    md_path = out / "paper.md"
    md_path.write_text(text, encoding="utf-8")
    chars = len(text)
    headings = len(re.findall(r"^#{1,3} ", text, re.M))
    warning = "" if chars >= 1500 else "文本过少，可能转换失败"
    return {
        "backend": "mineru",
        "md_path": str(md_path),
        "chars": chars,
        "headings": headings,
        "images": n_images,
        "elapsed": round(elapsed, 2),
        "warning": warning,
    }

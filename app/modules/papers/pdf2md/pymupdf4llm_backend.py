"""PyMuPDF4LLM 后端：PDF -> paper.md + assets/。"""
from __future__ import annotations

import re
import time
from pathlib import Path


def convert(pdf_path: str | Path, out_dir: str | Path, write_images: bool = True,
            dpi: int = 150) -> dict:
    import pymupdf4llm  # type: ignore

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    assets = out / "assets"
    assets.mkdir(exist_ok=True)

    t0 = time.time()
    if write_images:
        md = pymupdf4llm.to_markdown(
            str(pdf_path), write_images=True, image_path=str(assets),
            image_format="png", dpi=dpi,
        )
    else:
        md = pymupdf4llm.to_markdown(str(pdf_path))
    elapsed = time.time() - t0

    md_path = out / "paper.md"
    md_path.write_text(md, encoding="utf-8")
    headings = len(re.findall(r"^#{1,3} ", md, re.M))
    n_images = len(list(assets.glob("*.png"))) if write_images else 0
    chars = len(md)

    warning = ""
    if chars < 1500:
        warning = "文本过少，可能是扫描版 PDF（需要 OCR 后端，如 MinerU）"
    elif headings <= 2:
        warning = "标题识别较少，报告质量可能受影响"

    return {
        "backend": "pymupdf4llm",
        "md_path": str(md_path),
        "chars": chars,
        "headings": headings,
        "images": n_images,
        "elapsed": round(elapsed, 2),
        "warning": warning,
    }

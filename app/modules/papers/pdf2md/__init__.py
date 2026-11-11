"""PDF -> Markdown 后端注册表。

默认 pymupdf4llm（轻量、无模型）；mineru（高质量，需外部安装 CLI）。
"""
from __future__ import annotations

from pathlib import Path

from . import mineru_backend, pymupdf4llm_backend

BACKENDS = {
    "pymupdf4llm": pymupdf4llm_backend.convert,
    "mineru": mineru_backend.convert,
}

LABELS = {
    "pymupdf4llm": "PyMuPDF4LLM（快）",
    "mineru": "MinerU（高质量）",
}


def convert(backend: str, pdf_path: str | Path, out_dir: str | Path, **kwargs) -> dict:
    if backend not in BACKENDS:
        raise ValueError(f"未知 PDF 后端：{backend}（可选：{', '.join(BACKENDS)}）")
    return BACKENDS[backend](pdf_path, out_dir, **kwargs)


def available() -> list[str]:
    return list(BACKENDS)


def mineru_available() -> bool:
    return mineru_backend.available()


def mineru_hint() -> str:
    return mineru_backend.version_hint()

"""文献模块设置（JSON，存 data/papers/settings.json）。"""
from __future__ import annotations

import json
from pathlib import Path

from .store import DATA_ROOT

SETTINGS_FILE = DATA_ROOT / "settings.json"

DEFAULTS = {
    "pdf_backend": "pymupdf4llm",     # pymupdf4llm | mineru
    "mineru_device": "cpu",           # cpu | cuda
    "mineru_cmd": "",                 # 可选：mineru 可执行文件路径
}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        if SETTINGS_FILE.is_file():
            data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    return data


def save(data: dict) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get(key: str, default=None):
    return load().get(key, default)


def set_value(key: str, value) -> None:
    data = load()
    data[key] = value
    save(data)

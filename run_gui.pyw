#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""入口：启动 MechLab 主壳（COMSOL 提交 + 文献 → 报告）。"""
import sys
import traceback
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _write_crash_log() -> None:
    try:
        logs = _base_dir() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "startup_error.log").write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    sys.path.insert(0, str(_base_dir()))
    from app.shell import main as run

    run()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        _write_crash_log()
        raise

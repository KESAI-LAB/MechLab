"""自定义机器：machines.json 的读写、注册进 config.MACHINES。

内置机器（K/A/E/M）来自 config.py；用户通过「接入新机」页面添加的机器
存到 machines.json（含私钥路径，已被 .gitignore 排除），启动时合并。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import MACHINE_BY_LABEL, MACHINES, PROJECT_ROOT, Machine

MACHINES_FILE = PROJECT_ROOT / "machines.json"
BUILTIN_KEYS = {"K", "A", "E", "M"}


@dataclass
class CustomMachine:
    key: str = ""
    label: str = ""
    host: str = ""
    port: int = 22
    key_path: str = ""
    base_win: str = ""
    base_unix: str = ""
    batch: str = ""
    compile: str = ""
    cores: int = 8
    supports_boundary: bool = True
    engine: str = "remote_extract"

    def validate(self) -> None:
        if not self.label.strip():
            raise ValueError("显示名不能为空")
        if "@" not in self.host:
            raise ValueError("主机要写成 user@host")
        if not self.key_path.strip():
            raise ValueError("私钥路径不能为空")
        if not self.base_win.strip():
            raise ValueError("远程工作目录（Windows 形式）不能为空")
        if not self.batch.strip():
            raise ValueError("comsolbatch 路径不能为空")
        if not self.compile.strip():
            raise ValueError("comsolcompile 路径不能为空")
        if self.cores < 1:
            raise ValueError("核数必须 ≥ 1")
        self.port = int(self.port or 22)
        self.base_unix = self.base_unix.strip() or self.base_win.replace("\\", "/")

    def to_extra(self) -> dict:
        return {
            "host": self.host.strip(),
            "port": int(self.port),
            "key_path": self.key_path.strip(),
            "base_win": self.base_win.strip(),
            "base_unix": self.base_unix.strip(),
            "batch": self.batch.strip(),
            "compile": self.compile.strip(),
            "engine": self.engine,
            "cores": int(self.cores),
        }


def _read() -> list[dict]:
    if not MACHINES_FILE.is_file():
        return []
    try:
        data = json.loads(MACHINES_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    return data if isinstance(data, list) else []


def _write(rows: list[dict]) -> None:
    MACHINES_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _new_key(existing: set[str]) -> str:
    i = 1
    while f"U{i}" in MACHINES or f"U{i}" in existing:
        i += 1
    return f"U{i}"


def _register(cm: CustomMachine) -> Machine:
    m = Machine(
        key=cm.key,
        label=cm.label,
        cores=int(cm.cores),
        backend="GenericRemote",
        supports_boundary=bool(cm.supports_boundary),
        note=f"{cm.host} · 端口 {cm.port}",
        extra=cm.to_extra(),
    )
    MACHINES[cm.key] = m
    MACHINE_BY_LABEL[cm.label] = m
    return m


def load_into_config() -> int:
    """启动时把 machines.json 里的机器合并进 MACHINES。返回加载数量。"""
    n = 0
    for row in _read():
        try:
            cm = CustomMachine(**row)
            cm.validate()
        except Exception:  # noqa: BLE001
            continue
        if cm.key in BUILTIN_KEYS or cm.key in MACHINES:
            continue
        _register(cm)
        n += 1
    return n


def list_custom() -> list[CustomMachine]:
    out = []
    for row in _read():
        try:
            cm = CustomMachine(**row)
            cm.validate()
            out.append(cm)
        except Exception:  # noqa: BLE001
            continue
    return out


def save_machine(cm: CustomMachine) -> Machine:
    """新增或更新一台自定义机器，并写入 machines.json。"""
    cm.validate()
    rows = _read()
    existing_keys = {r.get("key") for r in rows}
    if not cm.key or cm.key in BUILTIN_KEYS:
        cm.key = _new_key(existing_keys)
    # 同名 label 更新
    rows = [r for r in rows if r.get("key") != cm.key]
    rows.append(asdict(cm))
    _write(rows)
    return _register(cm)


def remove_machine(key: str) -> None:
    if key in BUILTIN_KEYS:
        raise ValueError("内置机器不能删除")
    rows = [r for r in _read() if r.get("key") != key]
    _write(rows)
    m = MACHINES.pop(key, None)
    if m is not None:
        MACHINE_BY_LABEL.pop(m.label, None)

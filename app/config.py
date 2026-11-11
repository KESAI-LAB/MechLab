"""全局配置：机器定义、默认探针、路径解析。
新增一台机器只要在 MACHINES 里加一条，并在 backends.py 里加对应类。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path


def _project_root() -> Path:
    """源码运行 = 仓库根；PyInstaller 打包后 = exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


# app/config.py -> parents[1] 是仓库根目录
PROJECT_ROOT = _project_root()
APP_DIR = PROJECT_ROOT          # 兼容旧语义：APP_DIR = 仓库根（logs/jobs/docs/engine 都在这下面）
ENGINE_DIR = PROJECT_ROOT / "engine"
REMOTE_DIR = ENGINE_DIR / "remote"
DOCS_DIR = PROJECT_ROOT / "docs"
REPO = PROJECT_ROOT          # 兼容旧代码里的 REPO 引用（bash 命令的工作目录）

DEFAULT_STUDY = "std1"
APP_NAME = "MechLab"
APP_VERSION = "v2.0-dev"      # 界面标题里显示，便于确认打开的是新版本

#: 任务日志与任务存档
LOG_DIR = APP_DIR / "logs"
JOBS_FILE = APP_DIR / "jobs.json"

#: 默认探针（域探针，三台机器都支持）
DEFAULT_SPEC = (
    "SiC_hoop=solid.sphi@2;"
    "SiCin_hoop=solid.sphi@b13,18;"
    "IPyC_hoop=solid.sphi@4,5;"
    "band_d=phi@6;"
    "Int_d=phi@3"
)

#: 纯域探针（E 机只能用它）
DEFAULT_SPEC_DOMAIN_ONLY = (
    "SiC_hoop=solid.sphi@2;"
    "IPyC_hoop=solid.sphi@4,5;"
    "band_d=phi@6;"
    "Int_d=phi@3"
)


@dataclass
class Machine:
    key: str                 # 内部标识
    label: str               # 下拉框显示
    cores: int               # 默认核数
    backend: str             # backends.py 里的类名
    supports_boundary: bool  # 是否支持 @b… 边界探针
    note: str = ""           # 界面提示
    extra: dict = field(default_factory=dict)


MACHINES: dict[str, Machine] = {
    "K": Machine(
        key="K", label="K 本机", cores=8, backend="LocalK",
        supports_boundary=True, note="本机 COMSOL（需按本机路径配置）",
    ),
    "A": Machine(
        key="A", label="远程 A（示例）", cores=30, backend="RemoteA",
        supports_boundary=True,
        note="示例槽位：把自己的主机写进 engine/remote/env_oldA.sh",
    ),
    "E": Machine(
        key="E", label="远程 E（示例）", cores=22, backend="RemoteE",
        supports_boundary=False,
        note="示例槽位：把自己的主机写进 engine/remote/env_evior.sh；不支持 @b 边界探针",
    ),
    "M": Machine(
        key="M", label="M 演示模式（Mock）", cores=1, backend="MockBackend",
        supports_boundary=True, note="低碳钢拉伸演示 · 约15秒 · 自动生成曲线",
    ),
}

MACHINE_BY_LABEL = {m.label: m for m in MACHINES.values()}


def label_list() -> list[str]:
    return [m.label for m in MACHINES.values()]

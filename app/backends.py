"""提交后端：把 (模型, 探针, 研究步, 核数, 标签) 变成一条 bash 命令。

每个后端负责两件事：
    build_command()        —— 一次求解 + 提取的完整命令
    build_probe_command()  —— 只测连通性（ssh / COMSOL 是否存在），几秒钟出结果

新增机器时：
    1. config.MACHINES 里加一条（backend 写类名）
    2. 这里继承 Backend 实现两个方法
    3. BACKENDS 里注册
"""
from __future__ import annotations

import os

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from .config import MACHINES, REPO

STUDY_RE = re.compile(r"^[A-Za-z0-9_, ]*$")   # 允许空（=全部）、单个、逗号列表


def q(s: str) -> str:
    return shlex.quote(s)


@dataclass
class Job:
    model: str
    spec: str
    study: str
    cores: int
    tag: str
    save_solution: bool = False

    def env_prefix(self) -> str:
        """是否让引擎保存解模型（各机器写到自己的 solutions 目录）。"""
        return "KEEP_SOLVED=1 " if self.save_solution else ""


class Backend:
    name = "base"

    def __init__(self, machine_key: str | None = None):
        self.machine_key = machine_key

    def validate(self, job: Job) -> None:
        if not job.model:
            raise ValueError("请先选择模型文件")
        if not Path(job.model).is_file():
            raise ValueError(f"模型不存在：{job.model}")
        if not job.spec.strip():
            raise ValueError("探针表达式不能为空")
        if job.cores < 1:
            raise ValueError("核数必须 ≥ 1")
        if not STUDY_RE.match(job.study):
            raise ValueError("研究步只能填字母/数字/下划线/逗号，例如 std1 或 std1,std2；留空=全部")
        if not job.tag.strip():
            raise ValueError("输出标签不能为空")

    def build_command(self, job: Job) -> str:  # pragma: no cover
        raise NotImplementedError

    def build_probe_command(self) -> str:  # pragma: no cover
        raise NotImplementedError

    def build_abort_command(self) -> str:
        """中止时清理这台机器上残留的 comsolbatch。"""
        return "echo '[abort] nothing to do'"


class LocalK(Backend):
    name = "local-k"
    ENGINE = REPO / "engine" / "local_extract.sh"
    BATCH = os.environ.get(
        "COMSOL_BATCH",
        "/f/Program Files/COMSOL/COMSOL64/Multiphysics/bin/win64/comsolbatch.exe")

    def validate(self, job: Job) -> None:
        super().validate(job)
        if not self.ENGINE.is_file():
            raise ValueError(f"缺少本机引擎脚本：{self.ENGINE}")

    def build_command(self, job: Job) -> str:
        return (f"{job.env_prefix()}bash {q(str(self.ENGINE))} {q(job.model)} {q(job.spec)} "
                f"{q(job.study)} {job.cores} {q(job.tag)}")

    def build_probe_command(self) -> str:
        return (f'if [ -f "{self.BATCH}" ]; then echo COMSOL_OK; else echo COMSOL_MISSING; fi; '
                f'echo "本机核数: $(nproc 2>/dev/null || echo ?)"')

    def build_abort_command(self) -> str:
        return 'taskkill //IM comsolbatch.exe //F 2>/dev/null; echo "[abort] local comsolbatch killed"' 


class RemoteA(Backend):
    name = "remote-a"
    ENV = "engine/remote/env_oldA.sh"
    SCRIPT = "engine/remote/remote_extract.sh"

    def validate(self, job: Job) -> None:
        super().validate(job)
        for p in (self.ENV, self.SCRIPT):
            if not (REPO / p).is_file():
                raise ValueError(f"缺少脚本：{p}")

    def build_command(self, job: Job) -> str:
        return (f"source {self.ENV} && {job.env_prefix()}"
                f"bash {self.SCRIPT} {q(job.model)} - {q(job.spec)} "
                f"{q(job.study)} {job.cores} {q(job.tag)}")

    def build_probe_command(self) -> str:
        # ${RG_BATCH} 由 source 展开，$(...) 求值即得到 ssh 的返回
        return (f"source {self.ENV} && "
                f'ssh -i "$RG_KEY" -o BatchMode=yes -o ConnectTimeout=10 "$RG_HOST" '
                f'"echo LINK_OK && if exist \\"${{RG_BATCH}}\\" (echo COMSOL_OK) else (echo COMSOL_MISSING)" '
                f'2>&1; echo "host=$RG_HOST"')

    def build_abort_command(self) -> str:
        return (f"source {self.ENV} && "
                f'ssh -i "$RG_KEY" -o BatchMode=yes -o ConnectTimeout=10 "$RG_HOST" '
                f'"taskkill /IM comsolbatch.exe /F" 2>&1; echo "[abort] remote comsolbatch killed"')


class RemoteE(Backend):
    name = "remote-e"
    ENV = "engine/remote/env_evior.sh"
    SCRIPT = "engine/remote/emsolve_extract.sh"
    # 可选：覆盖 env 文件里的 RG_HOST；留空则使用 env 文件配置
    HOST = os.environ.get("RG_HOST", "").strip()

    def _prefix(self) -> str:
        prefix = f"source {self.ENV} && "
        if self.HOST:
            prefix += f"export RG_HOST={q(self.HOST)} && "
        return prefix

    def validate(self, job: Job) -> None:
        super().validate(job)
        for p in (self.ENV, self.SCRIPT):
            if not (REPO / p).is_file():
                raise ValueError(f"缺少脚本：{p}")
        if "@b" in job.spec:
            raise ValueError("E 机脚本不支持边界探针（@b…），请改用域探针，或提交到 K/A 机")

    def build_command(self, job: Job) -> str:
        #  emsolve_extract.sh <model> <cores> <tag> "<spec>" [studies]
        return (f"{self._prefix()}{job.env_prefix()}"
                f"bash {self.SCRIPT} {q(job.model)} {job.cores} {q(job.tag)} "
                f"{q(job.spec)} {q(job.study)}")

    def build_probe_command(self) -> str:
        return (f"{self._prefix()}"
                f'ssh -i "$RG_KEY" -o BatchMode=yes -o ConnectTimeout=10 "$RG_HOST" '
                f'"echo LINK_OK && if exist \\"${{RG_BATCH}}\\" (echo COMSOL_OK) else (echo COMSOL_MISSING)" '
                f'2>&1; echo "host=$RG_HOST"')

    def build_abort_command(self) -> str:
        return (f"{self._prefix()}"
                f'ssh -i "$RG_KEY" -o BatchMode=yes -o ConnectTimeout=10 "$RG_HOST" '
                f'"taskkill /IM comsolbatch.exe /F" 2>&1; echo "[abort] remote comsolbatch killed"')


class MockBackend(Backend):
    """演示模式：不连远程、不启 COMSOL，按固定节奏伪造日志并复制预置 CSV。"""

    name = "mock"
    ENGINE = REPO / "engine" / "mock_engine.sh"

    def build_command(self, job: Job) -> str:
        return (f"bash {q(str(self.ENGINE))} {q(job.model)} {q(job.spec)} "
                f"{q(job.study)} {job.cores} {q(job.tag)}")

    def build_probe_command(self) -> str:
        return 'echo "MOCK_OK（演示模式，不连远程）"'


class GenericRemote(Backend):
    """通用远程后端：连接参数全部来自 config.MACHINES[key].extra（machines.json）。

    复用 engine/remote/remote_extract.sh（Windows + OpenSSH + COMSOL 即可）。
    """

    name = "generic-remote"

    def _extra(self) -> dict:
        if not self.machine_key or self.machine_key not in MACHINES:
            raise ValueError("通用远程后端缺少机器配置（machine_key）")
        return MACHINES[self.machine_key].extra

    def _exports(self) -> str:
        e = self._extra()
        pairs = {
            "RG_HOST": e.get("host"),
            "RG_PORT": e.get("port", 22),
            "RG_KEY": e.get("key_path"),
            "RG_BASE_WIN": e.get("base_win"),
            "RG_BASE_UNIX": e.get("base_unix"),
            "RG_BATCH": e.get("batch"),
            "RG_COMPILE": e.get("compile"),
        }
        parts = [f"export {k}={q(str(v))}" for k, v in pairs.items() if v]
        return "; ".join(parts)

    def validate(self, job: Job) -> None:
        super().validate(job)
        e = self._extra()
        for key in ("host", "key_path", "base_win", "batch", "compile"):
            if not e.get(key):
                raise ValueError(f"机器配置缺少 {key}")

    def build_command(self, job: Job) -> str:
        script = REPO / "engine" / "remote" / "remote_extract.sh"
        return (f"{self._exports()}; {job.env_prefix()}"
                f"bash {q(str(script))} {q(job.model)} - {q(job.spec)} "
                f"{q(job.study)} {job.cores} {q(job.tag)}")

    def build_probe_command(self) -> str:
        e = self._extra()
        host = e.get("host", "")
        key = e.get("key_path", "")
        port = int(e.get("port", 22))
        batch = e.get("batch", "")
        return (f'ssh -i {q(key)} -p {port} -o BatchMode=yes -o StrictHostKeyChecking=no '
                f'-o ConnectTimeout=10 {q(host)} '
                f'"echo LINK_OK && if exist \\"{batch}\\" (echo COMSOL_OK) else (echo COMSOL_MISSING)" '
                f'2>&1; echo "host={host}"')

    def build_abort_command(self) -> str:
        e = self._extra()
        host = e.get("host", "")
        key = e.get("key_path", "")
        port = int(e.get("port", 22))
        return (f'ssh -i {q(key)} -p {port} -o BatchMode=yes -o StrictHostKeyChecking=no '
                f'{q(host)} "taskkill /IM comsolbatch.exe /F" 2>&1; echo "[abort] remote comsolbatch killed"')


BACKENDS: dict[str, type[Backend]] = {
    "LocalK": LocalK,
    "RemoteA": RemoteA,
    "RemoteE": RemoteE,
    "MockBackend": MockBackend,
    "GenericRemote": GenericRemote,
}


def get_backend(name: str, machine_key: str | None = None) -> Backend:
    return BACKENDS[name](machine_key)

"""MOOSE 本地提交（WSL）任务队列：命令构建、运行、日志/进度、中止、通知。"""
from __future__ import annotations

import json
import os
import posixpath
import re
import shlex
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ... import notify
from ...config import PROJECT_ROOT
from ...runner import CREATE_NO_WINDOW

WSL = "wsl.exe"
LOG_DIR = PROJECT_ROOT / "logs" / "moose"
DATA_FILE = PROJECT_ROOT / "data" / "moose.json"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
ERR_RE = re.compile(
    r"(MOOSE error|ERROR|Segmentation|terminate called|Killed|out of memory|"
    r"PETSc|Unable to|not converged|failed|失败|错误|异常)", re.IGNORECASE)
PROGRESS_RE = re.compile(
    r"(Time Step\s+\d+|Solve Converged|dt\s*=|Nonlinear\s*\|\|R\||\|\|R\||"
    r"Step\s+\d+|Time\s*=\s*[0-9.eE+-]+)", re.IGNORECASE)

STATUS_TXT = {"pending": "排队中", "running": "运行中", "done": "完成 ✓",
              "failed": "失败 ✗", "cancelled": "已中止"}
STATUS_COLOR = {"pending": "#8a6d00", "running": "#0a6", "done": "#0a6",
                "failed": "#c33", "cancelled": "#777"}

_HOME_CACHE: dict[str, str] = {}


def clean(text: str) -> str:
    return ANSI_RE.sub("", text or "")


_STACK_RE = re.compile(r"^\d+:\s")
_NOISE_TOKENS = ("print_trace", "Stack frames", "+0x", "MPI_Abort",
                 "application called MPI_Abort")


def meaningful_lines(lines: list[str]) -> list[str]:
    """去掉 MOOSE 报错里的栈帧/噪声行，只留有用信息。"""
    out: list[str] = []
    for raw in lines:
        s = clean(raw).strip()
        if not s or _STACK_RE.match(s):
            continue
        if any(tok in s for tok in _NOISE_TOKENS):
            continue
        if s.startswith("***") or s.startswith("---"):
            continue
        out.append(s)
    return out


# --------------------------------------------------------------------------- WSL
def list_distros() -> list[str]:
    try:
        r = subprocess.run([WSL, "-l", "-q"], capture_output=True, timeout=10,
                           creationflags=CREATE_NO_WINDOW)
        raw = r.stdout or b""
        for enc in ("utf-16-le", "utf-8", "mbcs"):
            try:
                text = raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                return lines
    except Exception:  # noqa: BLE001
        pass
    return []


def default_distro() -> str:
    ds = list_distros()
    return ds[0] if ds else "Ubuntu"


def wsl_home(distro: str) -> str:
    if distro in _HOME_CACHE:
        return _HOME_CACHE[distro]
    home = "/home"
    try:
        r = subprocess.run([WSL, "-d", distro, "--", "bash", "-lc", 'printf %s "$HOME"'],
                           capture_output=True, timeout=15, creationflags=CREATE_NO_WINDOW)
        text = (r.stdout or b"").decode("utf-8", "replace").strip()
        if text:
            home = text
    except Exception:  # noqa: BLE001
        pass
    _HOME_CACHE[distro] = home
    return home


def to_wsl_path(path: str) -> str:
    """Windows 路径 -> WSL 路径；已经是 / 或 ~ 开头则原样返回。"""
    p = (path or "").strip().replace("\\", "/")
    if not p:
        return p
    if p.startswith("/") or p.startswith("~"):
        return p
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    if m:
        return f"/mnt/{m.group(1).lower()}/{m.group(2)}"
    for prefix in ("//wsl$/", "//wsl.localhost/"):
        if p.startswith(prefix):
            rest = p[len(prefix):].split("/", 1)
            return "/" + (rest[1] if len(rest) > 1 else "")
    return p


def resolve_path(path: str, distro: str) -> str:
    p = to_wsl_path(path)
    if p.startswith("~"):
        p = wsl_home(distro) + p[1:]
    return p


def wsl_test(distro: str, flag: str, path: str) -> bool:
    try:
        r = subprocess.run([WSL, "-d", distro, "--", "bash", "-lc",
                            f"test {flag} {shlex.quote(path)}"],
                           capture_output=True, timeout=15, creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- settings
DEFAULT_SETTINGS = {
    "distro": "",
    "app": "~/moose/examples/ex01_inputfile/ex01-opt",
    "mpi_cmd": "",
    "threads": 1,
    "env_cmd": "",
    "extra": "",
}


def load_settings() -> dict:
    data = dict(DEFAULT_SETTINGS)
    try:
        if DATA_FILE.is_file():
            data.update(json.loads(DATA_FILE.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    return data


def save_settings(data: dict) -> None:
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------- job
@dataclass
class MooseJob:
    id: str
    input_file: str            # 原始选择（Windows 或 WSL 路径）
    input_wsl: str
    workdir_wsl: str
    app: str
    distro: str
    mpi_cmd: str = ""
    threads: int = 1
    env_cmd: str = ""
    extra: str = ""
    tag: str = ""
    status: str = "pending"
    created: float = field(default_factory=time.time)
    started: float = 0.0
    ended: float = 0.0
    exit_code: int | None = None
    error: str = ""
    progress: str = ""
    outputs: list[str] = field(default_factory=list)
    log_path: str = ""

    @property
    def elapsed(self) -> float:
        if self.status == "running" and self.started:
            return time.time() - self.started
        if self.started and self.ended:
            return self.ended - self.started
        return 0.0

    @property
    def model(self) -> str:
        return self.input_wsl

    @property
    def cores(self) -> int:
        m = re.search(r"-n\s+(\d+)", self.mpi_cmd or "")
        return int(m.group(1)) if m else 1

    def describe(self) -> str:
        return f"{posixpath.basename(self.input_wsl)} · {self.tag}"


class MooseManager:
    """单 worker 串行队列（MOOSE 本地计算一般一次跑一个）。"""

    def __init__(self) -> None:
        self.jobs: dict[str, MooseJob] = {}
        self._queue: list[str] = []
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._cancel_ids: set[str] = set()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._worker, daemon=True).start()

    def log_path(self, job_id: str) -> Path:
        return LOG_DIR / f"{job_id}.log"

    def add(self, job: MooseJob) -> MooseJob:
        with self._lock:
            job.log_path = str(self.log_path(job.id))
            self.jobs[job.id] = job
            self._queue.append(job.id)
        return job

    def cancel(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        if job.status == "pending":
            with self._lock:
                if job_id in self._queue:
                    self._queue.remove(job_id)
                job.status = "cancelled"
                job.ended = time.time()
        elif job.status == "running":
            self._cancel_ids.add(job_id)
            proc = self._proc
            if proc and proc.poll() is None:
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   capture_output=True, timeout=10,
                                   creationflags=CREATE_NO_WINDOW)
                except Exception:  # noqa: BLE001
                    pass
            threading.Thread(target=self._pkill, args=(job,), daemon=True).start()

    def _pkill(self, job: MooseJob) -> None:
        name = posixpath.basename(job.input_wsl)
        try:
            subprocess.run([WSL, "-d", job.distro, "--", "bash", "-lc",
                            f"pkill -f -- {shlex.quote(name)} 2>/dev/null; true"],
                           capture_output=True, timeout=15, creationflags=CREATE_NO_WINDOW)
        except Exception:  # noqa: BLE001
            pass

    def remove(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job or job.status == "running":
            return
        with self._lock:
            self.jobs.pop(job_id, None)
            if job_id in self._queue:
                self._queue.remove(job_id)
        try:
            self.log_path(job_id).unlink(missing_ok=True)
        except OSError:
            pass

    def clear_finished(self) -> None:
        for j in list(self.jobs.values()):
            if j.status in ("done", "failed", "cancelled"):
                self.remove(j.id)

    def machine_busy(self) -> MooseJob | None:
        for j in self.jobs.values():
            if j.status == "running":
                return j
        return None

    # ------------------------------------------------------------------ worker
    def _worker(self) -> None:
        while True:
            job_id = None
            with self._lock:
                for jid in self._queue:
                    j = self.jobs.get(jid)
                    if j and j.status == "pending":
                        job_id = jid
                        self._queue.remove(jid)
                        break
            if not job_id:
                time.sleep(0.5)
                continue
            job = self.jobs.get(job_id)
            if job:
                self._run(job)

    def _build_command(self, job: MooseJob) -> str:
        parts: list[str] = []
        if job.env_cmd.strip():
            parts.append(job.env_cmd.strip())
        if job.mpi_cmd.strip():
            parts.append(job.mpi_cmd.strip())
        parts.append(shlex.quote(job.app))
        # MOOSE 的 -i 参数不接受含空格的路径（会被它按空白拆开），
        # 所以先 cd 到工作目录，再用文件名调用。
        parts += ["-i", shlex.quote(posixpath.basename(job.input_wsl))]
        if job.threads and job.threads > 1:
            parts += ["--n-threads", str(job.threads)]
        if job.extra.strip():
            parts.append(job.extra.strip())
        return f"cd {shlex.quote(job.workdir_wsl)} && " + " ".join(parts) + " 2>&1"

    def _run(self, job: MooseJob) -> None:
        job.status = "running"
        job.started = time.time()
        job.progress = "启动中…"
        log_path = self.log_path(job.id)
        cmd = self._build_command(job)
        try:
            proc = subprocess.Popen(
                [WSL, "-d", job.distro, "--", "bash", "-lc", cmd],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=CREATE_NO_WINDOW)
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.ended = time.time()
            job.error = f"启动失败：{exc}"
            self._notify(job)
            return
        self._proc = proc
        errors: list[str] = []
        try:
            with log_path.open("w", encoding="utf-8") as fh:
                fh.write(f"# MOOSE job {job.id}\n# distro: {job.distro}\n# command: {cmd}\n\n")
                fh.flush()
                if proc.stdout is not None:
                    for raw in proc.stdout:
                        line = clean(raw.rstrip("\r\n"))
                        fh.write(line + "\n")
                        fh.flush()
                        if PROGRESS_RE.search(line):
                            job.progress = line.strip()[:120]
                        if ERR_RE.search(line):
                            errors.append(line.strip())
                            if len(errors) > 60:
                                errors.pop(0)
                        if job.id in self._cancel_ids:
                            break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"[runner] {exc}")
        try:
            code = proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            code = proc.poll()
        self._proc = None
        job.exit_code = code if code is not None else -1
        job.ended = time.time()

        if job.id in self._cancel_ids:
            job.status = "cancelled"
            job.error = "已中止"
            self._cancel_ids.discard(job.id)
        elif job.exit_code == 0:
            job.status = "done"
            job.progress = "完成"
        else:
            job.status = "failed"
            useful = meaningful_lines(errors)
            job.error = " | ".join(useful[-3:])[:220] if useful else f"exit {job.exit_code}"
            job.progress = "失败"
        job.outputs = self._find_outputs(job)
        self._notify(job)

    def _find_outputs(self, job: MooseJob) -> list[str]:
        out: list[str] = []
        try:
            p = Path(job.input_file)
            if p.is_file():
                for f in sorted(p.parent.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True):
                    if f.stat().st_mtime >= job.started - 2:
                        out.append(str(f))
                        if len(out) >= 5:
                            break
        except OSError:
            pass
        if not out:
            try:
                r = subprocess.run(
                    [WSL, "-d", job.distro, "--", "bash", "-lc",
                     f"cd {shlex.quote(job.workdir_wsl)} && ls -1t *.csv 2>/dev/null | head -5"],
                    capture_output=True, text=True, timeout=15, creationflags=CREATE_NO_WINDOW)
                out = [line.strip() for line in (r.stdout or "").splitlines() if line.strip()]
            except Exception:  # noqa: BLE001
                pass
        return out

    def _notify(self, job: MooseJob) -> None:
        detail = ""
        if job.status == "failed":
            try:
                lines = self.log_path(job.id).read_text(encoding="utf-8", errors="replace").splitlines()
                useful = meaningful_lines(lines[-40:]) or lines[-5:]
                detail = "日志尾部：\n" + "\n".join(line[:140] for line in useful[-5:])
            except OSError:
                pass
        label = f"WSL（{job.distro}）"
        notify.notify_job(job, label, job.status, detail)


def new_job_id() -> str:
    return uuid.uuid4().hex[:8]

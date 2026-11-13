"""任务管理：按机器排队、并发执行、中止、持久化。

设计：
    Manager 维护三台机器各一条队列；每台机器只有一个 worker 线程，串行跑自己的任务。
    不同机器之间互不阻塞，所以可以同时把不同模型丢给 A / E / K。
    每个任务一个日志文件；任务列表存盘，重启后还能看到历史。
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .backends import Backend, Job as JobInput, get_backend
from .config import JOBS_FILE, LOG_DIR, MACHINES, REPO
from .notify import notify_job
from .runner import ProcessRunner, find_bash


@dataclass
class Job:
    id: str
    machine: str                 # "K" / "A" / "E"
    model: str
    spec: str
    study: str
    cores: int
    tag: str
    save_solution: bool = False
    status: str = "staged"       # staged / pending / running / done / failed / cancelled / interrupted
    created: float = field(default_factory=time.time)
    started: float = 0.0
    ended: float = 0.0
    exit_code: Optional[int] = None

    @property
    def elapsed(self) -> float:
        if self.status == "running" and self.started:
            return time.time() - self.started
        if self.started and self.ended:
            return self.ended - self.started
        return 0.0

    def describe(self) -> str:
        return f"{Path(self.model).name} · {self.tag}"


class Manager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.queues: dict[str, list[str]] = {k: [] for k in MACHINES}
        self.runners: dict[str, ProcessRunner] = {}
        self._abort_cmds: dict[str, str] = {}
        self._lock = threading.Lock()
        self.events: "queue.Queue[tuple]" = queue.Queue()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._load()
        for key in MACHINES:
            t = threading.Thread(target=self._worker, args=(key,), daemon=True)
            t.start()

    def register_machine(self, key: str) -> None:
        """运行时新增一台机器：建队列并启动 worker 线程（内置机器已在 __init__ 建过）。"""
        with self._lock:
            if key in self.queues:
                return
            self.queues[key] = []
        threading.Thread(target=self._worker, args=(key,), daemon=True).start()

    # ------------------------------------------------------------------ 持久化
    def _load(self) -> None:
        if not JOBS_FILE.is_file():
            return
        try:
            data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        for rec in data.get("jobs", []):
            try:
                j = Job(**rec)
            except TypeError:
                continue
            if j.status == "running":
                j.status = "interrupted"     # 上次没跑完
            elif j.status == "pending":
                j.status = "staged"          # 上次排了但没开始，回到待提交
            self.jobs[j.id] = j
        for m, ids in data.get("queues", {}).items():
            if m in self.queues:
                self.queues[m] = [i for i in ids if i in self.jobs and self.jobs[i].status == "pending"]

    def _save(self) -> None:
        tmp = JOBS_FILE.with_suffix(".tmp")
        data = {"jobs": [asdict(j) for j in self.jobs.values()],
                "queues": self.queues}
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(JOBS_FILE)

    # ------------------------------------------------------------------ 查询
    def log_path(self, job_id: str) -> Path:
        return LOG_DIR / f"{job_id}.log"

    def machine_busy(self, key: str) -> Optional[Job]:
        for j in self.jobs.values():
            if j.machine == key and j.status == "running":
                return j
        return None

    def list_jobs(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)

    # ------------------------------------------------------------------ 操作
    def add_job(self, mkey: str, job_in: JobInput, staged: bool = True) -> Job:
        backend = get_backend(MACHINES[mkey].backend, mkey)
        backend.validate(job_in)        # 抛 ValueError 给界面
        j = Job(id=uuid.uuid4().hex[:8], machine=mkey, model=job_in.model,
                spec=job_in.spec, study=job_in.study, cores=job_in.cores, tag=job_in.tag,
                save_solution=getattr(job_in, "save_solution", False),
                status="staged" if staged else "pending")
        with self._lock:
            self.jobs[j.id] = j
            self.queues[mkey].append(j.id)
            self._save()
        self.events.put(("added", j.id))
        return j

    def submit(self, job_ids: list[str]) -> int:
        """把“待提交(staged)”的任务真正排入执行队列。返回实际提交数量。"""
        n = 0
        with self._lock:
            for jid in job_ids:
                j = self.jobs.get(jid)
                if j and j.status == "staged":
                    j.status = "pending"
                    if jid not in self.queues.get(j.machine, []):
                        self.queues.setdefault(j.machine, []).append(jid)
                    n += 1
            self._save()
        for jid in job_ids:
            self.events.put(("changed", jid))
        return n

    def cancel(self, job_id: str) -> None:
        j = self.jobs.get(job_id)
        if not j:
            return
        if j.status in ("staged", "pending"):
            with self._lock:
                if job_id in self.queues.get(j.machine, []):
                    self.queues[j.machine].remove(job_id)
                j.status = "cancelled"
                j.ended = time.time()
                self._save()
            self.events.put(("changed", job_id))
            return
        if j.status != "running":
            return
        # 运行中：先杀本地进程树，再杀远端 comsolbatch
        runner = self.runners.get(j.machine)
        if runner:
            runner.stop()
        threading.Thread(target=self._abort_remote, args=(j.id,), daemon=True).start()
        j.status = "cancelled"
        j.ended = time.time()
        with self._lock:
            self._save()
        self.events.put(("changed", job_id))

    def _abort_remote(self, job_id: str) -> None:
        j = self.jobs.get(job_id)
        if not j:
            return
        try:
            backend = get_backend(MACHINES[j.machine].backend, j.machine)
            cmd = backend.build_abort_command()
        except Exception:  # noqa: BLE001
            return
        try:
            subprocess.run([find_bash(), "-lc", cmd], cwd=str(REPO),
                           capture_output=True, text=True, timeout=60,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        except Exception:  # noqa: BLE001
            pass

    def remove(self, job_id: str) -> None:
        j = self.jobs.get(job_id)
        if not j or j.status == "running":
            return
        with self._lock:
            self.jobs.pop(job_id, None)
            for q in self.queues.values():
                if job_id in q:
                    q.remove(job_id)
            self._save()
        try:
            self.log_path(job_id).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        self.events.put(("removed", job_id))

    def clear_finished(self) -> None:
        for j in list(self.jobs.values()):
            if j.status in ("done", "failed", "cancelled", "interrupted"):
                self.remove(j.id)

    # ------------------------------------------------------------------ 进度
    # COMSOL 批处理日志里的求解表行：  Step   Time   Stepsize ...
    _STEP_RE = re.compile(r"^\s{0,4}(\d+)\s+([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)\s+([-+0-9.eE]+)")
    _STEP_S_RE = re.compile(r"Step\s+\d+\s*:\s*Time\s*=\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)\s*s")

    def job_progress(self, job_id: str) -> tuple[str, bool]:
        """返回 (进度文字, 是否疑似卡住)。解析失败时退回“最后更新时间”。"""
        j = self.jobs.get(job_id)
        if not j:
            return "", False
        path = self.log_path(job_id)
        if not path.is_file():
            return "", False
        try:
            st = path.stat()
        except OSError:
            return "", False
        age = max(0.0, time.time() - st.st_mtime)
        stalled = j.status == "running" and age > 600      # 10 分钟没写日志
        if j.status != "running":
            return "", stalled

        parts: list[str] = []
        # 1) 我们在引擎里打的“第 i 步”
        mstep = None
        steps_total = len([x for x in j.study.split(",") if x.strip()])
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(max(0, st.st_size - 40000))
                tail = fh.read()
        except OSError:
            tail = ""
        for line in tail.splitlines():
            mm = re.search(r"第\s*(\d+)\s*步", line)
            if mm:
                mstep = int(mm.group(1))
        if mstep and steps_total:
            parts.append(f"研究 {mstep}/{steps_total}")
        # 2) 最后一条求解表行 / Mock 演示的 Step 行 → 当前物理时间
        tsec = None
        for line in reversed(tail.splitlines()):
            mm = self._STEP_S_RE.search(line)
            if mm:
                try:
                    tsec = float(mm.group(1))
                except ValueError:
                    continue
                break
        if tsec is None:
            for line in reversed(tail.splitlines()):
                mm = self._STEP_RE.match(line)
                if mm:
                    try:
                        tsec = float(mm.group(2))
                    except ValueError:
                        continue
                    break
        if tsec is not None and tsec > 0:
            if tsec < 3600:
                parts.append(f"t≈{tsec:.1f} s")
            elif tsec < 86400:
                parts.append(f"t≈{tsec / 60:.0f} min")
            else:
                parts.append(f"t≈{tsec / 86400:.0f} d")
        # 收敛性：求解表最后一行的 Tfail / NLfail
        nlfail = tfail = None
        for line in reversed(tail.splitlines()):
            mm = self._STEP_RE.match(line)
            if not mm:
                continue
            toks = line.split()
            try:
                if len(toks) >= 9:
                    tfail = int(float(toks[7]))
                    nlfail = int(float(toks[8]))
            except (ValueError, IndexError):
                pass
            break
        if nlfail:
            parts.append(f"· NLfail={nlfail}")
        if not parts:
            parts.append(f"日志 {int(age)} s 前更新")
        elif age > 120:
            parts.append(f"· {int(age // 60)} min 无更新")
        return " ".join(parts), stalled

    # ------------------------------------------------------------------ worker
    def _worker(self, mkey: str) -> None:
        while True:
            job_id = None
            with self._lock:
                q = self.queues.get(mkey, [])
                # 只取 pending；staged（待用户提交）留在队列里
                for idx, jid in enumerate(q):
                    jj = self.jobs.get(jid)
                    if jj and jj.status == "pending":
                        job_id = jid
                        q.pop(idx)
                        break
            if not job_id:
                time.sleep(1.0)
                continue
            j = self.jobs.get(job_id)
            if not j:
                continue
            self._run(mkey, j)

    def _run(self, mkey: str, j: Job) -> None:
        backend = get_backend(MACHINES[mkey].backend, mkey)
        job_in = JobInput(model=j.model, spec=j.spec, study=j.study, cores=j.cores,
                          tag=j.tag, save_solution=j.save_solution)
        cmd = backend.build_command(job_in)
        log = self.log_path(j.id)
        runner = ProcessRunner(cwd=str(REPO))
        self.runners[mkey] = runner
        j.status = "running"
        j.started = time.time()
        self.events.put(("changed", j.id))

        with log.open("w", encoding="utf-8") as fh:
            fh.write(f"# job {j.id}  machine={mkey}\n# command: {cmd}\n\n")
            fh.flush()

        def on_line(text: str) -> None:
            with log.open("a", encoding="utf-8") as fh:
                fh.write(text + "\n")

        try:
            runner.start(cmd)
        except Exception as exc:  # noqa: BLE001
            on_line(f"[manager] 启动失败：{exc}")
            j.status = "failed"
            j.ended = time.time()
            self.events.put(("changed", j.id))
            notify_job(j, MACHINES[mkey].label, "failed")
            return

        # 只以 runner 发出的 ("done", code) 事件作为结束信号；
        # 不要用 runner.running 判断——进程刚启动时 proc 可能还是 None，
        # 也不要调用 proc.wait()（会阻塞整个监控循环，日志和进度就停了）。
        done = {"code": None}

        def on_done(code: int) -> None:
            done["code"] = code

        while done["code"] is None:
            runner.drain(on_line, on_done)
            time.sleep(0.3)
        runner.drain(on_line, on_done)          # 收尾
        code = done["code"]

        j.exit_code = code
        j.ended = time.time()
        if j.status == "cancelled":
            pass
        elif code == 0:
            j.status = "done"
        else:
            j.status = "failed"
        self.runners.pop(mkey, None)
        with self._lock:
            self._save()
        self.events.put(("changed", j.id))
        notify_job(j, MACHINES[mkey].label, j.status)

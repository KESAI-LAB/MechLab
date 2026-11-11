"""进程执行器：后台跑 bash 命令，把输出按行回调给界面。

界面线程只读队列，不直接碰子进程，避免卡死。
"""
from __future__ import annotations

import os
import queue
import subprocess
import threading
from typing import Callable, Optional

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def decode_line(raw: bytes) -> str:
    """COMSOL 在中文 Windows 上输出 GBK，本地脚本输出 UTF-8，这里逐行自动识别。"""
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def find_bash() -> str:
    """找一个能识别 /f/… 与 Windows 路径的 MSYS/git bash。

    系统 PATH 里的 bash 可能是 WSL（/mnt/f/…），不能直接用于本项目的脚本。
    优先级：环境变量 DSH_BASH → dsh 自带 MSYS bash → git-bash → PATH 里的 bash（校验 OSTYPE）。
    """
    import glob
    import subprocess

    cands: list[str] = []
    if os.environ.get("DSH_BASH"):
        cands.append(os.environ["DSH_BASH"])
    cands += sorted(glob.glob(os.path.expanduser(
        r"~\.dsh\dsh-ops\shells\bash\*\usr\bin\bash.exe")), reverse=True)
    cands += [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    # 最后退回 PATH，但确认是 msys/mingw 而不是 WSL
    import shutil
    b = shutil.which("bash")
    if b:
        try:
            r = subprocess.run([b, "-c", "echo $OSTYPE"], capture_output=True, text=True, timeout=10)
            if "msys" in r.stdout.lower() or "mingw" in r.stdout.lower():
                return b
        except Exception:  # noqa: BLE001
            pass
    return b or "bash"


class ProcessRunner:
    def __init__(self, cwd: str):
        self.cwd = cwd
        self.bash = find_bash()
        self.proc: Optional[subprocess.Popen] = None
        self.queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._started_at: float = 0.0

    # ---------------------------------------------------------------- public
    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def elapsed(self) -> float:
        if not self._started_at:
            return 0.0
        import time
        return time.time() - self._started_at

    def start(self, command: str) -> None:
        if self.running:
            raise RuntimeError("已有任务在运行")

        def worker() -> None:
            import time
            self._started_at = time.time()
            try:
                self.proc = subprocess.Popen(
                    [self.bash, "-lc", command],
                    cwd=self.cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=False,
                    bufsize=0,
                    creationflags=CREATE_NO_WINDOW,
                )
                assert self.proc.stdout is not None
                for raw in self.proc.stdout:
                    self.queue.put(("line", decode_line(raw).rstrip(chr(13) + chr(10))))
                code = self.proc.wait()
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("line", f"[runner] 启动失败：{exc}"))
                code = -1
            self.queue.put(("done", code))

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """杀掉整棵进程树（bash → ssh/comsolbatch），否则 ssh 挂着看起来像没反应。"""
        if self.proc is None or self.proc.poll() is not None:
            return
        pid = self.proc.pid
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, timeout=30,
                               creationflags=CREATE_NO_WINDOW)
            else:
                self.proc.terminate()
        except Exception:  # noqa: BLE001
            try:
                self.proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        self.queue.put(("line", "[runner] 已中止（本地进程树已杀；远端 comsolbatch 由管理器另行清理）"))

    def drain(self, on_line: Callable[[str], None], on_done: Callable[[int], None]) -> None:
        """在当前线程（Tk 主线程）里调用，取出所有待处理消息。"""
        while True:
            try:
                kind, payload = self.queue.get_nowait()
            except queue.Empty:
                return
            if kind == "line":
                on_line(str(payload))
            elif kind == "done":
                on_done(int(payload))

"""任务通知：Bark（iPhone）推送，失败自动重试，不阻塞主流程。

配置存 data/notify.json（本地文件，已 gitignore，不会进仓库/安装包）。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .config import PROJECT_ROOT

SETTINGS_FILE = PROJECT_ROOT / "data" / "notify.json"
LOG_FILE = PROJECT_ROOT / "logs" / "notify.log"

DEFAULTS = {
    "enabled": True,
    "bark_key": "",
    "bark_server": "https://api.day.app",
    "group": "MechLab",
    "ttl": 600,
    "notify_done": True,
    "notify_failed": True,
}

STATUS_TXT = {
    "done": "任务完成",
    "failed": "任务失败",
    "cancelled": "任务已中止",
    "interrupted": "任务中断",
}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        if SETTINGS_FILE.is_file():
            data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    return data


def save(cfg: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.is_file() and LOG_FILE.stat().st_size > 256 * 1024:
            LOG_FILE.unlink()
    except OSError:
        pass


def _log(text: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except OSError:
        pass


def _bark_url(cfg: dict, title: str, body: str) -> str:
    server = (cfg.get("bark_server") or DEFAULTS["bark_server"]).rstrip("/")
    key = (cfg.get("bark_key") or "").strip()
    url = (f"{server}/{urllib.parse.quote(key, safe='')}/"
           f"{urllib.parse.quote(title, safe='')}/{urllib.parse.quote(body, safe='')}")
    params = {"group": cfg.get("group") or "MechLab"}
    try:
        params["ttl"] = str(int(cfg.get("ttl") or 600))
    except (TypeError, ValueError):
        params["ttl"] = "600"
    return url + "?" + urllib.parse.urlencode(params)


def send(title: str, body: str, cfg: dict | None = None) -> bool:
    """同步发送一条 Bark 通知；失败重试 2 次。"""
    cfg = cfg or load()
    if not (cfg.get("enabled", True) and str(cfg.get("bark_key") or "").strip()):
        return False
    url = _bark_url(cfg, title, body)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                raw = resp.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {}
            if int(payload.get("code", 200)) == 200:
                _log(f"sent: {title}")
                return True
            _log(f"failed(code): {title} -> {raw[:200]}")
        except Exception as exc:  # noqa: BLE001
            _log(f"error({attempt + 1}/3): {title} -> {exc}")
        time.sleep(2)
    return False


def send_async(title: str, body: str, cfg: dict | None = None) -> None:
    threading.Thread(target=send, args=(title, body, cfg), daemon=True).start()


def _fmt_elapsed(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, sec = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def notify_job(job, machine_label: str, status: str, detail: str = "") -> None:
    """任务结束回调：按配置异步推送。job 为 manager.Job。"""
    cfg = load()
    if not cfg.get("enabled", True):
        return
    if status == "done" and not cfg.get("notify_done", True):
        return
    if status == "failed" and not cfg.get("notify_failed", True):
        return
    if status not in ("done", "failed"):
        return
    title = f"MechLab · {STATUS_TXT.get(status, status)}"
    lines = [
        Path(job.model).name,
        f"{machine_label} · {job.tag} · {job.cores} 核",
        f"耗时 {_fmt_elapsed(job.elapsed)}" +
        (f" · exit {job.exit_code}" if job.exit_code is not None else ""),
    ]
    if getattr(job, "error", ""):
        lines.append("原因：" + str(job.error)[:200])
    body = "\n".join(lines)
    if detail:
        body += "\n\n" + detail.strip()
    send_async(title, body[:1000], cfg)


def test(cfg: dict | None = None) -> bool:
    return send("MechLab 通知测试", "Bark 推送配置成功", cfg)

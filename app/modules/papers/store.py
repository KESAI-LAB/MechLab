"""文献模块数据层：SQLite 索引 + 每篇文献一个目录。

data/papers/
├─ library.db
└─ <paper_id>/
   ├─ source.pdf
   ├─ paper.md          (PDF→Markdown 结果)
   ├─ assets/           (图片)
   ├─ extraction.json   (LLM 结构化抽取)
   ├─ theory.md         (理论报告)
   └─ implementation.md (COMSOL 实现报告)
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

from ...config import PROJECT_ROOT

DATA_ROOT = PROJECT_ROOT / "data" / "papers"
DB_PATH = DATA_ROOT / "library.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    title TEXT,
    pdf_path TEXT,
    md_path TEXT,
    status TEXT DEFAULT 'imported',
    chars INTEGER DEFAULT 0,
    headings INTEGER DEFAULT 0,
    images INTEGER DEFAULT 0,
    pages INTEGER DEFAULT 0,
    warning TEXT DEFAULT '',
    created REAL,
    updated REAL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT,
    kind TEXT,
    path TEXT,
    meta TEXT DEFAULT '',
    created REAL
);
CREATE INDEX IF NOT EXISTS idx_reports_paper ON reports(paper_id);
"""

_FIELDS = {"title", "md_path", "status", "chars", "headings", "images", "pages", "warning"}


def _conn() -> sqlite3.Connection:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


def _pdf_meta(pdf: Path) -> tuple[str, int]:
    try:
        import pymupdf  # type: ignore
        doc = pymupdf.open(str(pdf))
        title = ""
        try:
            title = (doc.metadata or {}).get("title", "") or ""
        except Exception:  # noqa: BLE001
            title = ""
        pages = doc.page_count
        doc.close()
        return title.strip(), int(pages)
    except Exception:  # noqa: BLE001
        return "", 0


def add_paper(pdf_path: str | Path, title: str | None = None) -> dict:
    src = Path(pdf_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"PDF 不存在：{src}")
    init_db()
    pid = uuid.uuid4().hex[:10]
    d = DATA_ROOT / pid
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, d / "source.pdf")

    meta_title, pages = _pdf_meta(d / "source.pdf")
    title = (title or meta_title or src.stem).strip()
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT INTO papers(id,title,pdf_path,status,pages,created,updated) VALUES(?,?,?,?,?,?,?)",
            (pid, title, str(d / "source.pdf"), "imported", pages, now, now),
        )
    return get_paper(pid)


def get_paper(pid: str) -> dict:
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
    return dict(row) if row else {}


def list_papers() -> list[dict]:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT * FROM papers ORDER BY created DESC").fetchall()
    return [dict(r) for r in rows]


def update_paper(pid: str, **fields) -> None:
    bad = set(fields) - _FIELDS
    if bad:
        raise ValueError(f"不允许更新字段：{bad}")
    if not fields:
        return
    init_db()
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [time.time(), pid]
    with _conn() as c:
        c.execute(f"UPDATE papers SET {sets}, updated=? WHERE id=?", vals)


def paper_dir(pid: str) -> Path:
    return DATA_ROOT / pid


def add_report(paper_id: str, kind: str, path: str | Path, meta: str = "") -> None:
    init_db()
    with _conn() as c:
        c.execute("INSERT INTO reports(paper_id,kind,path,meta,created) VALUES(?,?,?,?,?)",
                  (paper_id, kind, str(path), meta, time.time()))


def list_reports(paper_id: str) -> list[dict]:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT * FROM reports WHERE paper_id=? ORDER BY id", (paper_id,)).fetchall()
    return [dict(r) for r in rows]


def markdown_stats(md_text: str) -> dict:
    return {
        "chars": len(md_text),
        "headings": len(re.findall(r"^#{1,3} ", md_text, re.M)),
    }

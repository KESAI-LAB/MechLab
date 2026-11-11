"""图表处理：图注清单 + 图号映射（供报告插图使用）。

- MinerU 后端：解析 `mineru_raw/**/*_content_list.json`，其中 image 块自带
  `img_path` / `image_caption` / `page_idx`，映射精确；
- PyMuPDF4LLM：从 paper.md 里按"图片链接附近的 Fig./Figure 标题"做近似匹配，
  仅作兜底（图片位置常与图注错位，可能失败）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_CAP_START = re.compile(r"^(?:Fig(?:ure)?\.?|Table|图|表)\s*\d+", re.IGNORECASE)
_FIG_NUM = re.compile(r"(?:Fig(?:ure)?\.?|图)\s*(\d+)", re.IGNORECASE)
_IMG_LINK = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def extract_captions(md_text: str, limit: int = 80) -> list[str]:
    caps: list[str] = []
    seen: set[str] = set()
    for line in md_text.splitlines():
        s = re.sub(r"\s+", " ", line.strip())
        if not s or len(s) > 320:
            continue
        if _CAP_START.match(s):
            if s not in seen:
                seen.add(s)
                caps.append(s)
        if len(caps) >= limit:
            break
    return caps


def count_image_links(md_text: str) -> int:
    return len(_IMG_LINK.findall(md_text))


def write_figures_md(md_text: str, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    caps = extract_captions(md_text)
    lines = ["# 图表清单（从论文图注自动提取）", ""]
    lines += [f"{i}. {c}" for i, c in enumerate(caps, 1)]
    path = out / "figures.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"path": str(path), "count": len(caps), "image_links": count_image_links(md_text)}


def _clean_caption(caps) -> str:
    if isinstance(caps, str):
        caps = [caps]
    if not caps:
        return ""
    text = " ".join(str(c).strip() for c in caps if str(c).strip())
    return re.sub(r"\s+", " ", text).strip()


def _parse_from_content_list(paper_dir: Path) -> list[dict]:
    for cl in sorted(paper_dir.glob("mineru_raw/**/*_content_list.json")):
        try:
            blocks = json.loads(cl.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        figures: list[dict] = []
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "image":
                continue
            caption = _clean_caption(block.get("image_caption"))
            if not caption:
                continue
            img = Path(str(block.get("img_path", ""))).name
            if not (paper_dir / "assets" / img).is_file():
                continue
            m = _FIG_NUM.search(caption)
            num = int(m.group(1)) if m else len(figures) + 1
            figures.append({"num": num, "file": img, "caption": caption,
                            "page": block.get("page_idx")})
        if figures:
            return _dedupe(figures)
    return []


def _parse_from_markdown(paper_dir: Path, md_text: str) -> list[dict]:
    lines = md_text.splitlines()
    figures: list[dict] = []
    for i, line in enumerate(lines):
        for link in _IMG_LINK.findall(line):
            name = Path(link.replace("\\", "/")).name
            if not (paper_dir / "assets" / name).is_file():
                continue
            caption = ""
            for j in range(max(0, i - 8), min(len(lines), i + 9)):
                s = re.sub(r"\s+", " ", lines[j].strip())
                if _CAP_START.match(s) and len(s) <= 320:
                    caption = s
                    break
            if not caption:
                continue
            m = _FIG_NUM.search(caption)
            num = int(m.group(1)) if m else len(figures) + 1
            figures.append({"num": num, "file": name, "caption": caption, "page": None})
    return _dedupe(figures)


def _dedupe(figures: list[dict]) -> list[dict]:
    """同一图号只保留第一张（图可能被拆成多块）。"""
    seen: set[int] = set()
    out: list[dict] = []
    for fig in sorted(figures, key=lambda f: f["num"]):
        if fig["num"] in seen:
            continue
        seen.add(fig["num"])
        out.append(fig)
    return out


def build_figure_map(paper_dir: str | Path, md_text: str | None = None) -> dict:
    """生成 figures.json，返回 {source, figures:[{num,file,caption,page}]}。"""
    paper_dir = Path(paper_dir)
    md_text = md_text or (paper_dir / "paper.md").read_text(encoding="utf-8")

    figures = _parse_from_content_list(paper_dir)
    source = "mineru"
    if not figures:
        figures = _parse_from_markdown(paper_dir, md_text)
        source = "markdown" if figures else "none"

    data = {"source": source, "figures": figures}
    (paper_dir / "figures.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_figure_map(paper_dir: str | Path) -> dict:
    f = Path(paper_dir) / "figures.json"
    if f.is_file():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"source": "none", "figures": []}

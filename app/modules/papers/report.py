"""报告流水线：paper.md → 结构化 JSON → 理论报告 + COMSOL 实现报告。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import store
from .pdf2md import captions as pdf_captions
from .web import DeepSeekWeb

PROMPT_DIR = Path(__file__).parent / "prompts"
EXTRACT_PAPER_CHARS = 40000
REPORT_PAPER_CHARS = 22000


class ReportError(RuntimeError):
    pass


def _prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def _render(template: str, **kwargs) -> str:
    """占位符用 {name} 形式，但模板里含 JSON 花括号，所以用 replace 而不是 format。"""
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", value)
    return template


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.65)
    tail = limit - head
    return text[:head] + "\n\n[...中间内容省略...]\n\n" + text[-tail:]


def _lenient_json(body: str) -> str:
    """修复 LLM 输出里常见的非法 JSON 转义（LaTeX 反斜杠、尾逗号）。"""
    body = re.sub(r"\\u(?![0-9a-fA-F]{4})", r"\\\\u", body)          # \underline 之类
    body = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", body)               # \sigma / \frac …
    body = re.sub(r",\s*([}\]])", r"\1", body)                        # 尾逗号
    return body


def parse_json_block(raw: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    body = m.group(1) if m else raw
    if not m:
        i, j = body.find("{"), body.rfind("}")
        if i >= 0 and j > i:
            body = body[i:j + 1]
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        try:
            data = json.loads(_lenient_json(body))
        except Exception as exc:  # noqa: BLE001
            raise ReportError(f"抽取结果不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ReportError("抽取结果不是 JSON 对象")
    return data


def _paper_md(pid: str) -> str:
    p = store.get_paper(pid)
    md_path = p.get("md_path") or ""
    if not md_path or not Path(md_path).is_file():
        raise ReportError("还没有 paper.md，请先转 Markdown")
    md = Path(md_path).read_text(encoding="utf-8")
    figs = store.paper_dir(pid) / "figures.md"
    if figs.is_file():
        try:
            md += "\n\n" + figs.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return md


def _figure_map(pid: str) -> dict[int, dict]:
    data = pdf_captions.load_figure_map(store.paper_dir(pid))
    return {int(f["num"]): f for f in (data.get("figures") or [])}


def _figures_block(pid: str) -> str:
    figs = _figure_map(pid)
    if not figs:
        return "（本文没有可用的图片清单；不要插入任何 [[FIG:n]] 占位符。）"
    lines = ["可用原文图（n 只能取以下图号，每张最多引用一次）："]
    for num in sorted(figs):
        fig = figs[num]
        lines.append(f"- [[FIG:{num}]] 文件: assets/{fig['file']} | 图注: {fig['caption']}")
    return "\n".join(lines)


_FIG_MARK = re.compile(r"\[\[\s*FIG\s*[:：]?\s*(\d+)\s*\]\]", re.IGNORECASE)
_UI_ARTIFACT = re.compile(r"(?:markdown|text|plaintext|java|python|json|bash)?复制下载")


def _strip_ui_artifacts(text: str) -> str:
    """去掉网页代码块附带的语言标签/“复制下载”按钮文字。"""
    text = _UI_ARTIFACT.sub("", text)
    text = re.sub(r"^\s*(?:markdown|text|plaintext|java|python|json|bash)\s*$", "",
                  text, flags=re.MULTILINE)
    return text


def _move_images_out_of_code(text: str) -> str:
    """图片（连同其下方的图注）若落在 ``` 代码块内，移到代码块之后。"""
    lines = text.splitlines()
    result: list[str] = []
    pending: list[str] = []
    in_code = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            result.append(line)
            if in_code:
                in_code = False
                if pending:          # 关闭代码块后再放图片
                    result.append("")
                    result.extend(pending)
                    pending = []
            else:
                in_code = True
            i += 1
            continue
        if in_code and "![Fig." in line:
            block = [line]
            j = i + 1
            while j < len(lines) and (lines[j].strip() == ""
                                      or lines[j].strip().startswith("*Fig.")):
                block.append(lines[j])
                j += 1
            pending.extend(block)
            i = j
            continue
        result.append(line)
        i += 1
    if pending:
        result.append("")
        result.extend(pending)
    return "\n".join(result)


def _balance_fences(text: str) -> str:
    """代码围栏数为奇数时补一个结束围栏，避免后续 Markdown 被吞。"""
    if text.count("```") % 2 == 1:
        text = text.rstrip() + "\n```\n"
    return text


def insert_figures(text: str, pid: str) -> tuple[str, list[int], list[int]]:
    """把 [[FIG:n]] 替换成 Markdown 图片（assets/ 相对路径）。

    返回 (新文本, 已插入图号, 未找到图号)。
    """
    mapping = _figure_map(pid)
    used: list[int] = []
    missing: list[int] = []
    seen: set[int] = set()

    def repl(m: re.Match) -> str:
        num = int(m.group(1))
        fig = mapping.get(num)
        if fig is None:
            missing.append(num)
            return ""
        if num in seen:
            return ""
        seen.add(num)
        used.append(num)
        cap = re.sub(r"\s+", " ", str(fig.get("caption", ""))).strip()
        cap = cap.replace("[", "［").replace("]", "］")
        return f"\n\n![Fig. {num}](assets/{fig['file']})\n\n*{cap}*\n\n"

    out = _FIG_MARK.sub(repl, text)
    # 防止图片被拼在行内（模型偶尔不换行）
    out = re.sub(r"(?<!\n)(!\[Fig\.)", r"\n\1", out)
    out = _move_images_out_of_code(out)
    out = _balance_fences(out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"

    d = store.paper_dir(pid)
    if missing:
        (d / "figure_warnings.txt").write_text(
            "以下图号在正文里被引用，但图片清单中不存在，已忽略：\n"
            + ", ".join(str(n) for n in sorted(set(missing))) + "\n", encoding="utf-8")
    else:
        try:
            (d / "figure_warnings.txt").unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    return out, used, missing


def _ask(web: DeepSeekWeb, prompt: str, timeout: int = 600, prefer_code: bool = False) -> str:
    return web.ask(prompt, timeout=timeout, prefer_code=prefer_code)


def _run(web: DeepSeekWeb | None, login_timeout: int, fn):
    if web is not None:
        return fn(web)
    with DeepSeekWeb(login_timeout=login_timeout) as w:
        return fn(w)


def extract(pid: str, progress=None, login_timeout: int = 0,
            web: DeepSeekWeb | None = None) -> dict:
    md = _paper_md(pid)

    def job(w: DeepSeekWeb) -> dict:
        if progress:
            progress("正在抽取结构化信息（约 1–3 分钟）…")
        prompt = _render(_prompt("extract"), paper=truncate(md, EXTRACT_PAPER_CHARS))
        raw = _ask(w, prompt)
        (store.paper_dir(pid) / "extraction_raw.txt").write_text(raw, encoding="utf-8")
        data = parse_json_block(raw)
        (store.paper_dir(pid) / "extraction.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        store.update_paper(pid, status="extracted")
        return data

    return _run(web, login_timeout, job)


def _load_extraction(pid: str) -> dict:
    f = store.paper_dir(pid) / "extraction.json"
    if not f.is_file():
        raise ReportError("还没有 extraction.json，请先生成结构化信息")
    return json.loads(f.read_text(encoding="utf-8"))


def write_theory(pid: str, data: dict | None = None, progress=None,
                 login_timeout: int = 0, web: DeepSeekWeb | None = None) -> Path:
    md = _paper_md(pid)
    data = data or _load_extraction(pid)

    def job(w: DeepSeekWeb) -> Path:
        if progress:
            progress("正在生成理论报告（约 1–2 分钟）…")
        prompt = _render(_prompt("theory"),
                         extraction=json.dumps(data, ensure_ascii=False)[:20000],
                         figures=_figures_block(pid),
                         paper=truncate(md, REPORT_PAPER_CHARS))
        text = _ask(w, prompt, prefer_code=True)
        text = _strip_ui_artifacts(text)
        text, used, _missing = insert_figures(text, pid)
        if progress and used:
            progress(f"理论报告已插入 {len(used)} 张原文图")
        out = store.paper_dir(pid) / "theory.md"
        out.write_text(text, encoding="utf-8")
        store.add_report(pid, "theory", out)
        return out

    return _run(web, login_timeout, job)


def write_implementation(pid: str, data: dict | None = None, progress=None,
                         login_timeout: int = 0, web: DeepSeekWeb | None = None) -> Path:
    md = _paper_md(pid)
    data = data or _load_extraction(pid)

    def job(w: DeepSeekWeb) -> Path:
        if progress:
            progress("正在生成 COMSOL 实现报告（约 1–2 分钟）…")
        prompt = _render(_prompt("implementation"),
                         extraction=json.dumps(data, ensure_ascii=False)[:20000],
                         figures=_figures_block(pid),
                         paper=truncate(md, REPORT_PAPER_CHARS))
        text = _ask(w, prompt, prefer_code=True)
        text = _strip_ui_artifacts(text)
        text, used, _missing = insert_figures(text, pid)
        if progress and used:
            progress(f"实现报告已插入 {len(used)} 张原文图")
        out = store.paper_dir(pid) / "implementation.md"
        out.write_text(text, encoding="utf-8")
        store.add_report(pid, "implementation", out)
        return out

    return _run(web, login_timeout, job)


def run_all(pid: str, progress=None, login_timeout: int = 0) -> dict:
    """一次浏览器会话里跑完：抽取 → 理论报告 → 实现报告。"""
    results: dict = {}
    with DeepSeekWeb(login_timeout=login_timeout) as web:
        data = extract(pid, progress=progress, web=web)
        results["extraction"] = store.paper_dir(pid) / "extraction.json"
        results["theory"] = write_theory(pid, data, progress=progress, web=web)
        results["implementation"] = write_implementation(pid, data, progress=progress, web=web)
    store.update_paper(pid, status="done")
    if progress:
        progress("全部完成")
    return results

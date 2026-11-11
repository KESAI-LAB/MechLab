"""DeepSeek 网页版自动化后端（Playwright + 本机 Chrome 专用 profile）。

用法：
    with DeepSeekWeb() as web:
        ans = web.ask("用一句话解释相变")

设计原则：
- 登录态持久化在 .browser/deepseek_profile，第一次需要人工登录，之后自动复用；
- 单次只发一个请求，回答按"文本稳定"判定结束；
- 回答抓取时清掉按钮/引用角标等 UI 文本；
- 未登录/被风控时抛 LoginRequired / WebError，调用方决定降级。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from ...config import PROJECT_ROOT

ROOT = PROJECT_ROOT
DEFAULT_PROFILE = ROOT / ".browser" / "deepseek_profile"
URL = "https://chat.deepseek.com/"

INPUT_SELECTORS = ["textarea", "div[contenteditable='true']", "[role='textbox']"]
NEW_CHAT_SELECTORS = ["text=开启新对话", "button:has-text('开启新对话')", "text=新对话", "text=New chat"]

_EXTRACT_JS = """
() => {
  const sels = ['div.ds-markdown', 'div[class*="markdown"]', 'div[class*="Markdown"]'];
  let el = null;
  for (const s of sels) {
    const list = document.querySelectorAll(s);
    if (list.length) { el = list[list.length - 1]; break; }
  }
  if (!el) return '';
  const c = el.cloneNode(true);
  c.querySelectorAll('button, svg, sup, [class*="copy"], [class*="toolbar"], [class*="cite"], [class*="reference"]').forEach(n => n.remove());
  return c.innerText;
}
"""

_CODE_JS = """
() => {
  const pres = Array.from(document.querySelectorAll('pre'));
  if (!pres.length) return '';
  const el = pres[pres.length - 1];
  const code = el.querySelector('code') || el;
  return code.innerText || '';
}
"""


class LoginRequired(RuntimeError):
    pass


class WebError(RuntimeError):
    pass


def clean_answer(text: str) -> str:
    """去掉引用角标/工具条等残留行。"""
    lines = []
    for line in (text or "").splitlines():
        s = line.strip()
        if re.fullmatch(r"[-–—\s\d.]+", s):        # 纯数字/连字符行
            continue
        if re.fullmatch(r"[·•\s]*\d{1,2}(?:[ ·•]\d{1,2})*", s):
            continue
        lines.append(line.rstrip())
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


_TOOLBAR_RE = re.compile(r"(?:markdown|text|plaintext|java|python|json|bash)?复制下载")


def clean_code(text: str) -> str:
    """清理代码块抓取时附带的语言标签 / 复制下载按钮文字。"""
    t = _TOOLBAR_RE.sub("", text or "")
    t = re.sub(r"^\s*(?:markdown|text|plaintext|java|python|json|bash)\s*$", "", t,
               flags=re.MULTILINE)
    return clean_answer(t)


class DeepSeekWeb:
    def __init__(self, profile_dir: str | Path | None = None, headless: bool = False,
                 answer_timeout: int = 300, login_timeout: int = 0):
        self.profile_dir = Path(profile_dir) if profile_dir else DEFAULT_PROFILE
        self.headless = headless
        self.answer_timeout = answer_timeout
        self.login_timeout = login_timeout
        self._pw = None
        self._ctx = None
        self._page = None

    # ------------------------------------------------------------------ 生命周期
    def __enter__(self) -> "DeepSeekWeb":
        from playwright.sync_api import sync_playwright
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            channel="chrome",
            headless=self.headless,
            no_viewport=True,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            ignore_default_args=["--enable-automation"],
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1440,900",
                "--window-position=60,40",
            ],
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(1.5)
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._ctx is not None:
                self._ctx.close()
        finally:
            if self._pw is not None:
                self._pw.stop()
            self._ctx = None
            self._pw = None
            self._page = None

    # ------------------------------------------------------------------ 状态
    @property
    def page(self):
        if self._page is None:
            raise WebError("浏览器未启动")
        return self._page

    def _find_input(self):
        for sel in INPUT_SELECTORS:
            loc = self.page.locator(sel)
            try:
                for i in range(min(loc.count(), 6)):
                    el = loc.nth(i)
                    if el.is_visible():
                        return el, sel
            except Exception:  # noqa: BLE001
                continue
        return None, None

    def is_logged_in(self) -> bool:
        el, _ = self._find_input()
        return el is not None

    def ensure_login(self, timeout: int | None = None) -> None:
        timeout = self.login_timeout if timeout is None else timeout
        if self.is_logged_in():
            return
        if timeout <= 0:
            raise LoginRequired("DeepSeek 未登录（请先运行一次登录/探针脚本）")
        try:
            self.page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(3)
            if self.is_logged_in():
                return
            if int(time.time() - t0) % 60 < 3:
                try:
                    self.page.bring_to_front()
                except Exception:  # noqa: BLE001
                    pass
        raise LoginRequired(f"等待登录超时（{timeout}s）")

    # ------------------------------------------------------------------ 操作
    def new_chat(self) -> None:
        for sel in NEW_CHAT_SELECTORS:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    time.sleep(1.0)
                    return
            except Exception:  # noqa: BLE001
                continue
        self.page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(1.5)

    def ask(self, prompt: str, timeout: int | None = None, prefer_code: bool = False) -> str:
        timeout = timeout or self.answer_timeout
        self.ensure_login()
        self.new_chat()
        el, sel = self._find_input()
        if el is None:
            raise LoginRequired("找不到输入框（可能被登录页/验证码拦截）")

        try:
            el.click()
            self.page.keyboard.insert_text(prompt)
        except Exception:  # noqa: BLE001
            el.fill(prompt)
        time.sleep(0.6)
        self.page.keyboard.press("Enter")

        # 等回答稳定
        deadline = time.time() + timeout
        last, stable = "", 0
        while time.time() < deadline:
            time.sleep(1.5)
            text = self._last_answer()
            if text and text == last:
                stable += 1
            else:
                stable = 0
                last = text
            if stable >= 3 and text:
                if prefer_code:
                    code = self._last_code_block()
                    if code and len(code) > 50:
                        return clean_code(code)
                return clean_answer(text)
        if last:
            if prefer_code:
                code = self._last_code_block()
                if code and len(code) > 50:
                    return clean_code(code)
            return clean_answer(last)
        raise WebError("等待回答超时且未抓到内容")

    def _last_answer(self) -> str:
        try:
            return self.page.evaluate(_EXTRACT_JS) or ""
        except Exception:  # noqa: BLE001
            return ""

    def _last_code_block(self) -> str:
        try:
            return self.page.evaluate(_CODE_JS) or ""
        except Exception:  # noqa: BLE001
            return ""

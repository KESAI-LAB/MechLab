"""最小验证：Playwright + 本机 Chrome（专用 profile）操作 DeepSeek 网页版。

流程：
  1. 用专用 Chrome 用户目录打开 chat.deepseek.com（直连，无代理）；
  2. 等待你在窗口里手动登录（默认最多 10 分钟）；
  3. 检测到输入框后，自动发送一句测试问题；
  4. 等回答流式输出结束，抓取文本并保存。

用法：
  python scripts/deepseek_probe.py
  python scripts/deepseek_probe.py --login-timeout 600 --prompt "用一句话解释相变"
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / ".browser" / "deepseek_profile"
LOGS = ROOT / "logs"
URL = "https://chat.deepseek.com/"

INPUT_SELECTORS = ["textarea", "div[contenteditable='true']", "[role='textbox']"]
ANSWER_SELECTORS = ["div.ds-markdown", "div[class*='markdown']", "div[class*='Markdown']"]


def log(msg: str) -> None:
    print(f"[probe] {msg}", flush=True)


def find_visible(page, selectors: list[str]):
    for sel in selectors:
        loc = page.locator(sel)
        try:
            n = loc.count()
        except Exception:  # noqa: BLE001
            continue
        for i in range(min(n, 6)):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    return el, sel
            except Exception:  # noqa: BLE001
                continue
    return None, None


def page_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--login-timeout", type=int, default=900)
    ap.add_argument("--prompt", default="用一句话解释什么是相场断裂（phase-field fracture）。")
    ap.add_argument("--answer-timeout", type=int, default=180)
    args = ap.parse_args()

    LOGS.mkdir(parents=True, exist_ok=True)
    PROFILE.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        log("启动 Chrome（专用 profile，直连，无代理）...")
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="chrome",
            headless=False,
            no_viewport=True,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            ignore_default_args=["--enable-automation"],
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--start-maximized",
                "--window-size=1440,900",
                "--window-position=60,40",
            ],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)
        try:
            page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
        log(f"已打开：{page.title()}  {page.url}")

        # 检测是否已登录（有输入框）
        el, sel = find_visible(page, INPUT_SELECTORS)
        if el is None:
            log("未检测到输入框，等待你登录 DeepSeek ...")
            log(">>> 请在弹出的 Chrome 窗口里完成登录（扫码/密码），登录后停在聊天页即可。")
            t0 = time.time()
            while time.time() - t0 < args.login_timeout:
                time.sleep(3)
                el, sel = find_visible(page, INPUT_SELECTORS)
                if el is not None:
                    break
                # 每 60 秒把窗口提到前台，避免被其他窗口挡住
                if int(time.time() - t0) % 60 < 3:
                    try:
                        page.bring_to_front()
                    except Exception:  # noqa: BLE001
                        pass
                if int(time.time() - t0) % 30 < 3:
                    log(f"等待登录... {int(time.time()-t0)}s  (标题: {page.title()})  [窗口已置顶]")
            if el is None:
                log("登录等待超时，退出。")
                page.screenshot(path=str(LOGS / "deepseek_probe_timeout.png"))
                ctx.close()
                return 2

        log(f"已就绪，输入框选择器：{sel}")
        page.screenshot(path=str(LOGS / "deepseek_probe_ready.png"))

        # 发测试问题
        try:
            el.click()
            page.keyboard.insert_text(args.prompt)
        except Exception:  # noqa: BLE001
            el.fill(args.prompt)
        time.sleep(0.8)
        page.keyboard.press("Enter")
        log(f"已发送测试问题：{args.prompt}")

        # 等回答稳定
        deadline = time.time() + args.answer_timeout
        last, stable = "", 0
        while time.time() < deadline:
            time.sleep(2)
            txt = ""
            for s in ANSWER_SELECTORS:
                loc = page.locator(s)
                try:
                    if loc.count() > 0:
                        txt = loc.last.inner_text()
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not txt:
                txt = page_text(page)[-1500:]
            if txt and txt == last:
                stable += 1
            else:
                stable = 0
                last = txt
            if stable >= 3 and txt:
                break

        page.screenshot(path=str(LOGS / "deepseek_probe_done.png"))
        out = LOGS / "deepseek_probe_response.txt"
        out.write_text(last or "(未抓到回答)", encoding="utf-8")
        log("回答抓取完成：")
        log("-" * 60)
        log((last or "(未抓到回答)")[:2000])
        log("-" * 60)
        log(f"已保存：{out}")
        ctx.close()
        return 0


if __name__ == "__main__":
    sys.exit(main())

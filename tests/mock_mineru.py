"""测试用的假 MinerU CLI：模拟输出结构（<out>/<stem>/auto/<stem>.md + images/）。"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    pdf = args[args.index("-p") + 1]
    out = Path(args[args.index("-o") + 1])
    stem = Path(pdf).stem
    auto = out / stem / "auto"
    images = auto / "images"
    images.mkdir(parents=True, exist_ok=True)
    (images / "fig1.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"0" * 16)
    (auto / f"{stem}.md").write_text(
        f"# {stem}\n\n## 1 Intro\n\nMinerU mock content.\n\n![Fig1](images/fig1.png)\n",
        encoding="utf-8")
    print("mock mineru done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

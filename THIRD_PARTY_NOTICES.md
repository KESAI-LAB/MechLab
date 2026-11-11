# Third-Party Notices

MechLab's own source code is licensed under the MIT License (see `LICENSE`).
It depends on / optionally bundles the following third-party components. Their
licenses apply to those components; this file is a summary, not legal advice.

| Component | Used for | License |
|---|---|---|
| Python / Tkinter / Tcl-Tk | runtime & GUI | PSF License |
| [sv-ttk](https://github.com/rdbende/Sun-Valley-ttk-theme) | Windows 11 style theme | MIT |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) / [PyMuPDF4LLM](https://pypi.org/project/pymupdf4llm/) | PDF text/markdown extraction | **AGPL-3.0** (commercial license available from Artifex) |
| [MinerU](https://github.com/opendatalab/MinerU) (optional, external) | high-quality PDF → Markdown | **AGPL-3.0** |
| [Playwright](https://github.com/microsoft/playwright-python) | browser automation for DeepSeek web | Apache-2.0 |
| [Matplotlib](https://matplotlib.org/) | demo plots | Matplotlib License (PSF-based) |
| [NumPy](https://numpy.org/) | numerical dependency | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | image handling | HPND |
| [PyInstaller](https://pyinstaller.org/) | build tool (not runtime dependency) | GPL-2.0 with bootloader exception |

## Notes

- `PyMuPDF`/`PyMuPDF4LLM` are **AGPL-3.0**. If you redistribute the prebuilt
  installer (which bundles PyMuPDF), you must comply with AGPL: provide the
  corresponding source (this repository is the source) and keep license notices.
  For commercial/closed-source distribution, obtain a commercial license from
  Artifex or replace the PDF backend.
- `MinerU` is optional and is **not bundled**; if users install it, its AGPL
  terms apply independently.
- COMSOL, Ansys, Chrome and DeepSeek are trademarks/properties of their
  respective owners. MechLab is not affiliated with or endorsed by them.

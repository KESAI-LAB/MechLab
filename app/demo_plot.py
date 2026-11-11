"""演示模式「一键画图」：读取低碳钢拉伸 CSV，在 Tk 窗口里画应力-应变 / 载荷-位移。"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def _setup_cjk() -> None:
    import matplotlib
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False


def load_tensile(csv_path: str | Path) -> tuple[list[float], list[float], list[float], list[float]]:
    eps: list[float] = []
    sig: list[float] = []
    disp: list[float] = []
    load: list[float] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                eps.append(float(row["strain_pct"]))
                sig.append(float(row["stress_MPa"]))
                disp.append(float(row["disp_mm"]))
                load.append(float(row["load_kN"]))
            except (KeyError, TypeError, ValueError):
                continue
    if not eps:
        raise ValueError("CSV 里没有 strain_pct / stress_MPa 数据（不是演示拉伸数据）")
    return eps, sig, disp, load


def load_summary(path: str | Path | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def build_figure(csv_path: str | Path, summary_path: str | Path | None = None):
    """构造 Figure（不显示），便于测试与保存。"""
    _setup_cjk()
    from matplotlib.figure import Figure

    eps, sig, disp, load = load_tensile(csv_path)
    s = load_summary(summary_path)
    reh = float(s.get("ReH_MPa", 250.0))
    rel = float(s.get("ReL_MPa", 235.0))
    rm = float(s.get("Rm_MPa", max(sig)))
    a_pct = float(s.get("A_pct", eps[-1]))
    fmax = float(s.get("Fmax_kN", max(load)))

    fig = Figure(figsize=(10.6, 4.3), dpi=110)
    ax1, ax2 = fig.subplots(1, 2)

    ax1.plot(eps, sig, color="#c0392b", lw=2.1, label="工程应力-应变")
    for y in (reh, rel, rm):
        ax1.axhline(y, color="#95a5a6", ls=":", lw=0.9)
    ax1.annotate(f"ReH = {reh:.0f} MPa", xy=(min(0.4, eps[-1] * 0.1), reh),
                 xytext=(a_pct * 0.20, reh + 42), fontsize=8, color="#34495e",
                 arrowprops=dict(arrowstyle="->", color="#34495e", lw=0.8))
    ax1.annotate(f"ReL = {rel:.0f} MPa", xy=(min(1.0, eps[-1] * 0.2), rel),
                 xytext=(a_pct * 0.20, rel - 62), fontsize=8, color="#34495e",
                 arrowprops=dict(arrowstyle="->", color="#34495e", lw=0.8))
    ax1.annotate(f"Rm = {rm:.0f} MPa", xy=(eps[-1] * 0.77, rm),
                 xytext=(eps[-1] * 0.70, rm - 70), fontsize=8, color="#34495e",
                 arrowprops=dict(arrowstyle="->", color="#34495e", lw=0.8))
    ax1.annotate(f"A = {a_pct:.0f}%", xy=(a_pct, sig[-1]),
                 xytext=(a_pct * 0.78, sig[-1] + 45), fontsize=8, color="#34495e",
                 arrowprops=dict(arrowstyle="->", color="#34495e", lw=0.8))
    ax1.set_xlabel("工程应变 ε (%)")
    ax1.set_ylabel("工程应力 σ (MPa)")
    ax1.set_title("低碳钢拉伸 · 工程应力-应变", fontsize=10)
    ax1.grid(alpha=0.25)
    ax1.set_xlim(0, a_pct + 3.5)
    ax1.set_ylim(0, rm * 1.12)

    ax2.plot(disp, load, color="#2c3e50", lw=2.1)
    ax2.set_xlabel("位移 δ (mm)")
    ax2.set_ylabel("载荷 F (kN)")
    ax2.set_title("载荷-位移曲线", fontsize=10)
    ax2.grid(alpha=0.25)
    imax = max(range(len(load)), key=lambda i: load[i])
    ax2.annotate(f"Fmax = {fmax:.1f} kN", xy=(disp[imax], load[imax]),
                 xytext=(disp[-1] * 0.42, load[imax] * 0.82), fontsize=8, color="#34495e",
                 arrowprops=dict(arrowstyle="->", color="#34495e", lw=0.8))

    fig.tight_layout()
    return fig


def show_tensile_plot(master: tk.Misc, csv_path: str | Path, summary_path: str | Path | None = None) -> tk.Toplevel:
    """在独立窗口里显示图表（带工具栏与保存按钮）。"""
    fig = build_figure(csv_path, summary_path)
    s = load_summary(summary_path)

    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

    win = tk.Toplevel(master)
    win.title(f"一键画图（演示）· {Path(csv_path).name}")
    win.geometry("1120x640")
    win.minsize(900, 520)

    canvas = FigureCanvasTkAgg(fig, master=win)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True)

    toolbar = NavigationToolbar2Tk(canvas, win)
    toolbar.update()

    bottom = ttk.Frame(win)
    bottom.pack(fill="x", padx=8, pady=(2, 6))
    parts = [
        f"E={s.get('E_GPa', '?')} GPa",
        f"ReH={s.get('ReH_MPa', '?')} MPa",
        f"ReL={s.get('ReL_MPa', '?')} MPa",
        f"Rm={s.get('Rm_MPa', '?')} MPa",
        f"A={s.get('A_pct', '?')} %",
        f"Fmax={s.get('Fmax_kN', '?')} kN",
    ]
    ttk.Label(bottom, text="   |   ".join(parts)).pack(side="left")

    def save_png() -> None:
        out = filedialog.asksaveasfilename(
            parent=win, defaultextension=".png", filetypes=[("PNG 图片", "*.png")],
            initialfile=Path(csv_path).with_suffix(".png").name)
        if out:
            fig.savefig(out, dpi=180)
            messagebox.showinfo("已保存", out, parent=win)

    ttk.Button(bottom, text="保存图片…", command=save_png).pack(side="right")
    ttk.Button(bottom, text="关闭", command=win.destroy).pack(side="right", padx=6)
    return win

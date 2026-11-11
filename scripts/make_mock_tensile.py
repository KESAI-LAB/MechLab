"""生成 Mock 演示数据：低碳钢单轴拉伸（Q235 代表性曲线）。

产物（engine/mock_data/low_carbon_steel/）：
  tensile.csv        应变/应力/位移/载荷
  ts.csv             简化时间序列（兼容旧格式）
  steps.txt          求解日志的 20 个进度行
  stress_strain.png  工程应力-应变 + 载荷-位移图
  summary.json       关键指标（E/ReH/ReL/Rm/A/Fmax）

注意：这是**代表性合成数据**，用于演示流程，不是真实试验数据。
运行：python scripts/make_mock_tensile.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "engine" / "mock_data" / "low_carbon_steel"

# --- 材料参数（Q235 低碳钢代表性值） --------------------------------------
E_MPA = 206_000.0
REH = 250.0          # 上屈服强度 MPa
REL = 235.0          # 下屈服强度 MPa
RM = 420.0           # 抗拉强度 MPa
A_FRAC = 0.26        # 断后伸长率（工程应变）
L0_MM = 50.0         # 标距
A0_MM2 = 100.0       # 原始横截面积（20 mm × 5 mm）


def build_curve() -> dict:
    eps = np.concatenate([
        np.linspace(0.0, 0.0015, 60),      # 弹性段（略过屈服点）
        np.linspace(0.0015, 0.02, 260),    # 屈服平台（吕德斯带）
        np.linspace(0.02, 0.20, 420),      # 强化段
        np.linspace(0.20, A_FRAC, 140),    # 颈缩段
    ])
    eps = np.unique(eps)
    sig = np.zeros_like(eps)

    m = eps <= 0.0012
    sig[m] = E_MPA * eps[m]

    m = (eps > 0.0012) & (eps <= 0.02)
    sig[m] = REL + (REH - REL) * np.exp(-(eps[m] - 0.0012) / 0.0004) \
             + 2.0 * np.sin(2 * np.pi * (eps[m] - 0.0012) / 0.004)
    sig[m] = np.minimum(sig[m], REH)

    m = (eps > 0.02) & (eps <= 0.20)
    u = (eps[m] - 0.02) / (0.20 - 0.02)
    sig[m] = REL + (RM - REL) * (u ** 0.55)

    m = eps > 0.20
    u = (eps[m] - 0.20) / (A_FRAC - 0.20)
    sig[m] = RM - (RM - 330.0) * (u ** 0.8)

    disp = eps * L0_MM                      # mm
    load = sig * A0_MM2 / 1000.0            # kN
    return {"eps": eps, "sig": sig, "disp": disp, "load": load}


def write_csv(path: Path, curve: dict) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["strain_pct", "stress_MPa", "disp_mm", "load_kN"])
        for e, s, d, l in zip(curve["eps"], curve["sig"], curve["disp"], curve["load"]):
            w.writerow([f"{e*100:.4f}", f"{s:.4f}", f"{d:.4f}", f"{l:.4f}"])


def write_ts(path: Path, curve: dict) -> None:
    """简化时间序列：每 ~5% 应变取一个点（兼容"探针"风格）。"""
    idx = np.linspace(0, len(curve["eps"]) - 1, 21).round().astype(int)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame", "time_s", "stress_MPa", "strain_pct", "load_kN"])
        for k, i in enumerate(idx, start=1):
            w.writerow([k, f"{(k-1)*0.75:.2f}", f"{curve['sig'][i]:.2f}",
                        f"{curve['eps'][i]*100:.3f}", f"{curve['load'][i]:.3f}"])


def write_steps(path: Path, curve: dict) -> None:
    idx = np.linspace(0, len(curve["eps"]) - 1, 20).round().astype(int)
    lines = []
    for k, i in enumerate(idx, start=1):
        t = (k - 1) * 0.75
        lines.append(
            f"Step {k:2d} : Time = {t:5.2f} s   Load = {curve['load'][i]:6.2f} kN   "
            f"Strain = {curve['eps'][i]*100:5.2f} %")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_figure(path: Path, curve: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MultipleLocator

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.4))
    eps_pct, sig = curve["eps"] * 100, curve["sig"]
    ax1.plot(eps_pct, sig, color="#c0392b", lw=2.2, label="工程应力-应变")
    ax1.axhline(REH, color="#7f8c8d", ls=":", lw=1)
    ax1.axhline(REL, color="#7f8c8d", ls=":", lw=1)
    ax1.axhline(RM, color="#7f8c8d", ls=":", lw=1)
    ax1.annotate(f"ReH = {REH:.0f} MPa", xy=(0.3, REH), xytext=(4.5, 285),
                 fontsize=8, color="#34495e",
                 arrowprops=dict(arrowstyle="->", color="#34495e", lw=0.8))
    ax1.annotate(f"ReL = {REL:.0f} MPa", xy=(0.9, REL), xytext=(4.0, 205),
                 fontsize=8, color="#34495e",
                 arrowprops=dict(arrowstyle="->", color="#34495e", lw=0.8))
    ax1.annotate(f"Rm = {RM:.0f} MPa", xy=(20.0, RM), xytext=(22.2, RM - 62),
                 fontsize=8, color="#34495e",
                 arrowprops=dict(arrowstyle="->", color="#34495e", lw=0.8))
    ax1.annotate(f"A = {A_FRAC*100:.0f}%", xy=(A_FRAC * 100, sig[-1]), xytext=(20.8, 300),
                 fontsize=8, color="#34495e",
                 arrowprops=dict(arrowstyle="->", color="#34495e", lw=0.8))
    ax1.set_xlabel("工程应变 ε (%)")
    ax1.set_ylabel("工程应力 σ (MPa)")
    ax1.set_title("低碳钢（Q235 代表性曲线）", fontsize=10)
    ax1.grid(alpha=0.25)
    ax1.set_xlim(0, A_FRAC * 100 + 2.5)
    ax1.set_ylim(0, RM * 1.12)
    ax1.xaxis.set_major_locator(MultipleLocator(5))

    # 屈服平台局部放大
    ax1.inset_axes([0.10, 0.50, 0.34, 0.36])
    axins = ax1.child_axes[0]
    axins.plot(eps_pct, sig, color="#c0392b", lw=1.6)
    axins.set_xlim(0.0, 2.4)
    axins.set_ylim(190, 270)
    axins.tick_params(labelsize=6)
    axins.set_title("屈服平台放大", fontsize=7)
    axins.grid(alpha=0.2)

    ax2.plot(curve["disp"], curve["load"], color="#2c3e50", lw=2.2)
    ax2.set_xlabel("位移 δ (mm)")
    ax2.set_ylabel("载荷 F (kN)")
    ax2.set_title("载荷-位移曲线", fontsize=10)
    ax2.grid(alpha=0.25)
    ax2.annotate(f"Fmax = {curve['load'].max():.1f} kN",
                 xy=(curve["disp"][np.argmax(curve["load"])], curve["load"].max()),
                 xytext=(curve["disp"].max() * 0.45, curve["load"].max() * 0.86),
                 fontsize=8, color="#34495e",
                 arrowprops=dict(arrowstyle="->", color="#34495e", lw=0.8))

    plt.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    curve = build_curve()
    write_csv(OUT / "tensile.csv", curve)
    write_ts(OUT / "ts.csv", curve)
    write_steps(OUT / "steps.txt", curve)
    write_figure(OUT / "stress_strain.png", curve)

    imax = int(np.argmax(curve["sig"]))
    summary = {
        "material": "低碳钢 Q235（代表性合成数据）",
        "E_GPa": round(E_MPA / 1000.0, 1),
        "ReH_MPa": REH, "ReL_MPa": REL, "Rm_MPa": RM,
        "A_pct": round(A_FRAC * 100, 1),
        "Fmax_kN": round(float(curve["load"].max()), 2),
        "disp_at_Fmax_mm": round(float(curve["disp"][imax]), 2),
        "L0_mm": L0_MM, "A0_mm2": A0_MM2,
        "source": "synthetic representative of Q235 low-carbon steel (demo only)",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[mock-data] 生成完成 ->", OUT)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

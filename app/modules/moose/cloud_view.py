"""MOOSE 结果云图（二维优先，PyVista 离屏渲染）。

模块化说明
----------
这是可选模块：
- 删除本文件；
- 在 `app/modules/moose/ui.py` 里删除顶部 `from .cloud_view import ...` 的
  try/except 段、`if open_exodus_view is not None: self._build_results_panel(...)`
  那一行，以及 `_build_results_panel/_scan_results/choose_exodus/plot_result/
  open_result_dir/remove_result` 这组方法（还有工具栏「🖼 云图」按钮段）。
其余代码不依赖本模块。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .runner import LOG_DIR, MooseJob

VIEW_DIR = LOG_DIR / "cloud"
CACHE_DIR = VIEW_DIR / "cache"
_META_ARRAYS = {
    "ElementBlockIds", "Title", "Info_Records", "ObjectId", "QA_Records",
    "NodeSetIds", "SideSetIds", "EdgeSetIds", "FaceSetIds",
    "ElemSideSetIds", "GlobalNodeIds", "GlobalElementIds",
}


def _cache_dir() -> Path:
    """返回纯 ASCII 的可写缓存目录（VTK 不支持非 ASCII 路径）。"""
    candidates = [CACHE_DIR, Path(tempfile.gettempdir()) / "mechlab_cloud"]
    for cand in candidates:
        if all(ord(ch) < 128 for ch in str(cand)):
            try:
                cand.mkdir(parents=True, exist_ok=True)
                return cand
            except OSError:
                continue
    return CACHE_DIR


def _ascii_read_path(exodus: Path) -> Path:
    """VTK/Exodus 不能打开含中文等非 ASCII 的路径，先复制到纯 ASCII 缓存再读。"""
    if all(ord(ch) < 128 for ch in str(exodus)):
        return exodus
    try:
        st = exodus.stat()
    except OSError:
        return exodus
    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(
        f"{exodus}|{st.st_mtime_ns}|{st.st_size}".encode("utf-8")).hexdigest()[:16]
    dst = cache / f"{key}.e"
    if not dst.is_file() or dst.stat().st_size != st.st_size:
        shutil.copy2(exodus, dst)
    try:
        cutoff = time.time() - 3 * 86400
        for old in cache.glob("*.e"):
            if old != dst and old.stat().st_mtime < cutoff:
                old.unlink(missing_ok=True)
    except OSError:
        pass
    return dst


def _iter_grids(data):
    """递归遍历 PyVista 数据里的所有网格块（Exodus 是嵌套 MultiBlock）。"""
    try:
        arrays = getattr(data, "array_names", None)
        if arrays is not None:
            yield data
    except Exception:  # noqa: BLE001
        pass
    try:
        keys = list(data.keys())
    except Exception:  # noqa: BLE001
        keys = []
    for key in keys:
        try:
            child = data[key]
        except Exception:  # noqa: BLE001
            continue
        yield from _iter_grids(child)


def _pv():
    try:
        import pyvista as pv  # noqa: F401
        return pv
    except Exception:  # noqa: BLE001
        return None


def wsl_to_win(path: str, distro: str) -> str | None:
    """把 WSL 路径转成 Windows 可访问路径（/mnt/f -> F:\\，/home -> \\\\wsl.localhost）。"""
    p = (path or "").replace("\\", "/")
    if p.startswith("/mnt/") and len(p) > 6:
        drive, rest = p[5], p[7:]
        return f"{drive.upper()}:\\" + rest.replace("/", "\\")
    if p.startswith("/"):
        return f"\\\\wsl.localhost\\{distro}" + p.replace("/", "\\")
    return None


def find_exodus(job: MooseJob) -> Path | None:
    """在任务目录里找最新的 *_out.e。"""
    candidates: list[Path] = []
    try:
        p = Path(job.input_file)
        if p.is_file():
            candidates.append(p.parent)
    except OSError:
        pass
    win_dir = wsl_to_win(job.workdir_wsl, job.distro)
    if win_dir:
        candidates.append(Path(win_dir))
    for d in candidates:
        try:
            if not d.is_dir():
                continue
            files = sorted(d.glob("*_out.e"),
                           key=lambda f: f.stat().st_mtime, reverse=True)
            if files:
                return files[0]
        except OSError:
            continue
    return None


def load_grid(exodus: Path):
    """读 Exodus，返回可渲染的网格（合并 Element Blocks）。"""
    pv = _pv()
    if pv is None:
        raise RuntimeError("未安装 pyvista（pip install pyvista）")
    data = pv.read(str(_ascii_read_path(exodus)))
    keys = list(data.keys()) if hasattr(data, "keys") else []
    if "Element Blocks" in keys:
        blocks = data["Element Blocks"]
        return blocks.combine() if hasattr(blocks, "combine") else blocks
    if hasattr(data, "combine"):
        return data.combine()
    return data


def variables(exodus: Path) -> list[str]:
    """收集这个 .e 里所有可画的变量（含点/单元数据，过滤元数据）。"""
    pv = _pv()
    if pv is None:
        raise RuntimeError("未安装 pyvista（pip install pyvista）")
    data = pv.read(str(_ascii_read_path(exodus)))
    names: list[str] = []
    for grid in _iter_grids(data):
        for name in (getattr(grid, "array_names", None) or []):
            if name not in _META_ARRAYS and name not in names:
                names.append(name)
    return names


def render(exodus: Path, var: str, out_png: Path,
           cmap: str = "viridis") -> Path:
    """渲染一张静态云图；二维模型自动正对 XY 平面。"""
    pv = _pv()
    if pv is None:
        raise RuntimeError("未安装 pyvista（pip install pyvista）")
    grid = load_grid(exodus)
    if var not in (getattr(grid, "array_names", None) or []):
        grid = None
        for g in _iter_grids(pv.read(str(_ascii_read_path(exodus)))):
            if var in (getattr(g, "array_names", None) or []):
                grid = g
                break
    if grid is None:
        raise ValueError(f"变量不存在：{var}")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    pl = pv.Plotter(off_screen=True, window_size=(1100, 760))
    try:
        pl.add_mesh(grid, scalars=var, cmap=cmap, show_edges=True,
                    edge_color="#555555", line_width=0.3,
                    scalar_bar_args={"title": var})
        xmin, xmax, ymin, ymax, zmin, zmax = grid.bounds
        flat = abs(zmax - zmin) <= max(1e-9, 1e-6 * max(abs(zmin), abs(zmax), 1.0))
        if flat:
            pl.view_xy()
        else:
            pl.view_isometric()
        pl.add_text(f"{exodus.name} · {var}", position="upper_left", font_size=11)
        pl.screenshot(str(out_png))
    finally:
        pl.close()
    return out_png


def _safe_stem(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", (text or "result").strip()) or "result"


def open_cloud_view(parent, job: MooseJob) -> None:
    """按任务找最新 *_out.e，然后打开画图对话框。"""
    exodus = find_exodus(job)
    if exodus is None:
        messagebox.showwarning(
            "云图",
            "没找到 *_out.e 结果文件。\n\n"
            "MOOSE 需要开启 Exodus 输出（[Outputs] 里 exodus = true），"
            "并且任务目录里要有 .e 文件。",
            parent=parent)
        return
    open_exodus_view(parent, exodus)


def open_exodus_view(parent, exodus: Path) -> None:
    """直接对某个 .e 文件打开画图对话框：选变量 → 生成 PNG → 预览/另存/打开。"""
    if _pv() is None:
        messagebox.showwarning(
            "云图", "未安装 pyvista，无法出图。\n可在命令行执行：\n  pip install pyvista",
            parent=parent)
        return
    try:
        vars_ = variables(exodus)
    except Exception as exc:  # noqa: BLE001
        messagebox.showerror("云图", f"读取 {exodus.name} 失败：\n{exc}", parent=parent)
        return
    if not vars_:
        messagebox.showwarning(
            "云图",
            f"{exodus.name} 里没有可画的变量。\n\n"
            "常见原因：\n"
            "1. 选到了网格文件（如 mug.e / square.e），不是求解结果；\n"
            "2. 这个 .e 只有元数据，没有节点/单元变量。\n\n"
            "请选择 MOOSE 的求解结果 *_out.e（需要 [Outputs] exodus = true）。\n\n"
            f"文件：{exodus}",
            parent=parent)
        return

    win = tk.Toplevel(parent)
    win.title(f"云图 · {exodus.name}")
    win.transient(parent)
    win.geometry("1060x760")
    win.minsize(720, 520)

    top = ttk.Frame(win, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="变量").pack(side="left")
    var = tk.StringVar(value=vars_[0])
    combo = ttk.Combobox(top, textvariable=var, values=vars_, state="readonly", width=28)
    combo.pack(side="left", padx=6)
    ttk.Label(top, text="配色").pack(side="left", padx=(12, 0))
    cmap = tk.StringVar(value="viridis")
    ttk.Combobox(top, textvariable=cmap, state="readonly", width=12,
                 values=["viridis", "jet", "rainbow", "coolwarm", "plasma", "inferno"]).pack(
        side="left", padx=6)
    gen_btn = ttk.Button(top, text="生成云图")
    gen_btn.pack(side="left", padx=(12, 4))
    ttk.Button(top, text="另存为…", command=lambda: save_as()).pack(side="left", padx=4)
    ttk.Button(top, text="打开图片", command=lambda: open_img()).pack(side="left", padx=4)
    ttk.Button(top, text="关闭", command=win.destroy).pack(side="right")

    info = tk.StringVar(value=f"等待生成（{exodus}）")
    ttk.Label(win, textvariable=info, foreground="#6b7280").pack(fill="x", padx=10)

    holder = ttk.Frame(win)
    holder.pack(fill="both", expand=True, padx=8, pady=6)
    img_label = ttk.Label(holder, anchor="center")
    img_label.pack(fill="both", expand=True)

    state: dict = {"png": None, "photo": None, "busy": False}

    def show_png(path: Path) -> None:
        try:
            from PIL import Image, ImageTk
        except Exception:  # noqa: BLE001
            return
        try:
            img = Image.open(path)
            img.thumbnail((1000, 600))
            photo = ImageTk.PhotoImage(img)
            img_label.configure(image=photo)
            state["photo"] = photo
        except Exception:  # noqa: BLE001
            pass

    def generate() -> None:
        if state["busy"]:
            return
        state["busy"] = True
        state["done"] = False
        state["err"] = ""
        gen_btn.configure(state="disabled")
        info.set("正在渲染…")
        selected = var.get()
        selected_cmap = cmap.get() or "viridis"
        out = VIEW_DIR / f"{_safe_stem(exodus.stem)}_{_safe_stem(selected)}.png"
        state["png"] = out

        def work():
            try:
                render(exodus, selected, out, selected_cmap)
            except Exception as exc:  # noqa: BLE001
                state["err"] = str(exc)
            state["done"] = True

        threading.Thread(target=work, daemon=True).start()

        def poll() -> None:
            if not win.winfo_exists():
                return
            if not state.get("done"):
                win.after(150, poll)
                return
            state["busy"] = False
            gen_btn.configure(state="normal")
            if state.get("err"):
                info.set("生成失败")
                messagebox.showerror("云图", state["err"], parent=win)
                return
            info.set(f"已生成：{out}")
            show_png(out)

        win.after(150, poll)

    def open_img() -> None:
        png = state["png"]
        if png and Path(png).is_file():
            try:
                os.startfile(str(png))  # noqa: S606
            except Exception:  # noqa: BLE001
                pass

    def save_as() -> None:
        png = state["png"]
        if not png:
            messagebox.showinfo("云图", "先点「生成云图」", parent=win)
            return
        dst = filedialog.asksaveasfilename(
            parent=win, title="保存云图", defaultextension=".png",
            filetypes=[("PNG 图片", "*.png")],
            initialfile=Path(png).name)
        if dst:
            try:
                Path(dst).write_bytes(Path(png).read_bytes())
                info.set(f"已另存：{dst}")
            except OSError as exc:
                messagebox.showerror("保存失败", str(exc), parent=win)

    gen_btn.configure(command=generate)
    generate()

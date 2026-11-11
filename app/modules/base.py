"""模块基类：主壳只负责挂载，模块自己建 UI。"""
from __future__ import annotations

from tkinter import ttk


class BaseModule(ttk.Frame):
    """所有功能模块的基类。

    子类约定：
      - 类属性 title：标签页显示名；
      - 在 __init__ 里把控件建到 self 上；
      - on_show()：切到该页时调用（可选）；
      - on_app_close()：主窗口关闭前调用，返回 False 可阻止关闭（可选）。
    """

    title = "模块"

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

    def on_show(self) -> None:
        pass

    def on_app_close(self) -> bool:
        return True

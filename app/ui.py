"""兼容旧入口：界面已拆分到 app/modules/submitter/ui.py。"""
from .modules.submitter.ui import SubmitterPage as App

__all__ = ["App"]

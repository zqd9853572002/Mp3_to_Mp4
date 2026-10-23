# -*- coding: utf-8 -*-
"""应用启动层：隐藏控制台、创建 Tk 根窗口、安装异常兜底并进入主循环。

顶层 try/except 保留拆分前的行为：失败时打印 traceback，并尽力弹窗提示。
"""

import sys
import traceback
import tkinter as tk
from tkinter import messagebox

from .ui.main_window import AudioToVideoApp


def _hide_console() -> None:
    """🛑 隐藏 Windows 黑窗口（异常由 main() 统一弹窗提示）。"""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
        except Exception:
            pass


def _start() -> None:
    try:
        root = tk.Tk()
    except Exception:
        print(traceback.format_exc())
        return

    def report_exception(exc, value, tb):
        detail = "".join(traceback.format_exception(exc, value, tb))
        try:
            messagebox.showerror("程序异常", detail[-1500:])
        except Exception:
            print(detail)

    root.report_callback_exception = report_exception
    AudioToVideoApp(root)
    root.mainloop()


def main() -> None:
    _hide_console()
    try:
        _start()
    except Exception:
        trace = traceback.format_exc()
        print(trace)
        try:
            fallback = tk.Tk()
            fallback.withdraw()
            messagebox.showerror("启动失败", trace[-1500:])
            fallback.destroy()
        except Exception:
            pass

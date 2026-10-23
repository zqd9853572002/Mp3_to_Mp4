# -*- coding: utf-8 -*-
"""通用界面构件：带边框的分组容器、控件行、说明文字与复选框。

只放**通用**构件（不含任何业务语义），供 main_window 组合使用。
"""

import tkinter as tk

BG_PANEL = "#252526"
FG_TITLE = "#9CDCFE"
FG_CAPTION = "#CCCCCC"
FONT_UI = ("Microsoft YaHei", 9)


def group(parent, title, bg=BG_PANEL, border="#3C3C3C", title_fg=FG_TITLE):
    """带边框的分组容器，返回可放行的内层 Frame。"""
    outer = tk.Frame(parent, bg=bg, highlightbackground=border,
                     highlightthickness=1)
    outer.pack(fill="x", padx=20, pady=(0, 8))
    inner = tk.Frame(outer, bg=bg)
    inner.pack(fill="x", padx=10, pady=8)
    tk.Label(inner, text=title, bg=bg, fg=title_fg, anchor="w",
             font=("Microsoft YaHei", 9, "bold")).pack(fill="x", pady=(0, 4))
    return inner


def row(parent, bg=BG_PANEL):
    """控件行容器（横向排列的父级）。"""
    container = tk.Frame(parent, bg=bg)
    container.pack(fill="x", pady=2)
    return container


def caption(parent, text, bg=BG_PANEL, fg=FG_CAPTION, width=9):
    """行首的固定宽度说明文字。"""
    return tk.Label(parent, text=text, bg=bg, fg=fg, width=width,
                    anchor="w", font=FONT_UI)


def checkbutton(parent, text, variable, command=None, bg=BG_PANEL):
    """深色主题复选框（统一样式，避免各处参数漂移）。"""
    return tk.Checkbutton(
        parent, text=text, variable=variable, command=command, bg=bg,
        fg=FG_CAPTION, selectcolor="#2D2D30", activebackground=bg,
        activeforeground="white", font=FONT_UI, anchor="w")

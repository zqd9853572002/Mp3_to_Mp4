# -*- coding: utf-8 -*-
"""UI 子包：通用构件与主窗口。

界面文案已全部外置到 `mp3tom4/locale/*.json`，通过 `mp3tom4.i18n.t()` 取得，
本包不再持有任何中文文案模块。
"""

from .main_window import AudioToVideoApp

__all__ = ["AudioToVideoApp"]

# -*- coding: utf-8 -*-
"""极速音频转 MP4 批量引擎（YouTube 音频存档专用）。

给批量音频垫上一张静态图片，以 1 FPS 渲染成视频，并可选地做语音识别字幕与
两级降噪。核心引擎为 FFmpeg 子进程直调，不依赖 Python 媒体库。

模块划分：
* `config`   常量、配置持久化、路径与下载工具
* `ffmpeg`   FFmpeg 探测与成片封装
* `denoise`  RNNoise（ffmpeg arnndn）/ GTCRN（sherpa-onnx）降噪
* `asr`      faster-whisper 语音识别
* `subtitle` SRT / TXT 字幕生成
* `pipeline` 任务编排（降噪 / 识别 / 封装任意组合）
* `ui`       Tkinter 界面
* `i18n`     运行时三语词条层

版本号与 `config.APP_VERSION` 保持单一来源；历史开发日志见仓库根
`CHANGELOG.md`。
"""

from .config import APP_VERSION

__version__ = APP_VERSION

__all__ = ["__version__"]

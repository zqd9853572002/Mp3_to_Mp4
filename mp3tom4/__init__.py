# -*- coding: utf-8 -*-
"""
====================================================================
项目名称：极速音频转 MP4 批量引擎 (YouTube 音频存档专用)
核心引擎：FFmpeg（子进程直调，无需 Python 媒体库）
功能描述：给批量音频垫上一张静态图片，以 1 FPS 渲染成视频，用于 YouTube 等平台存档。
作    者：ZQD
====================================================================

【开发日志 / Changelog】

v4.1 (组合式任务版)
  - 界面重构：三卡式布局改为「单输入 + 选项 A / 选项 B 组合勾选 + 一个执行按钮」。
  - 任务计划：降噪、字幕（SRT / TXT 独立勾选）、原声配图 MP4、降噪配图 MP4 可任意组合，
    降噪音频一次生成、多处复用；只勾降噪选项时也能单独产出降噪音频。
  - 渲染：新增 48kHz 双声道降噪音频成片路径（RNNoise 保留 48k / GTCRN 16k 处理后上采样）。
  - 健壮性：工作线程整体异常兜底、取消可真正终止 ffmpeg 子进程、产物统一防覆盖。

v4.0 (语音识别 / 降噪字幕版)
  - 语音识别：集成 faster-whisper（CTranslate2 推理），音频/视频转写为文字，输出同名 .srt 字幕与 .txt 文本。
  - 混合语种：默认自动检测，中英混说无需手动切换；也可强制指定中文或英文。
  - 模型可选：large-v3-turbo（1.55GB，默认，精度优先）/ medium / small（464MB，速度快）/ base / tiny。
  - 前置降噪：RNNoise（ffmpeg arnndn，0.3MB，零额外依赖）与 GTCRN 神经网络（sherpa-onnx，0.5MB）两级可选。
    降噪只作用于「送去识别的音频」，成片 MP4 的音轨始终保持原始音质。
  - 渲染逻辑不变：仍是 1 FPS 静态图 + AAC 192k，字幕以旁挂文件形式输出，方便 YouTube 单独上传。

v3.0 (FFmpeg 引擎版)
  - 引擎切换：由 MoviePy 改为直接调用 FFmpeg 子进程。速度更快、内存占用更低，且不再依赖 Python 媒体库。
  - 多格式支持：MP3 / M4A / AAC / WAV / FLAC / OGG / OPUS / WMA / AIFF / APE 等 ffmpeg 可解的所有音频。
  - 封面适配：默认输出 1920x1080，等比缩放 + 黑边补齐；可切换「原图尺寸 / 1080p / 720p」。
  - YouTube 兼容：libx264 + yuv420p + faststart + AAC 192k，上传即可识别。
  - 体验增强：实时百分比进度、可中途取消、记住上次设置、同名输出自动加序号不覆盖。
  - 健壮性：自动探测系统中的 ffmpeg（PATH / winget / 程序同目录 / 常见安装路径 / imageio-ffmpeg），
            并在启动失败时弹窗提示，不再“双击无反应”。

v2.1 (MoviePy 2.x 适配版)
  - 语法重构：适配 MoviePy v2.0+ API，`set_duration`/`set_audio` 替换为 `with_duration`/`with_audio`。
  - 核心引擎升级：直接从 `moviepy` 根目录引入核心类。

v1.0 (极速渲染奠基版)
  - 架构确立：引入 MoviePy 作为调度引擎，底层隐式调用 FFmpeg 混流封装。
  - 核心算法优化：强制视频帧率 1 FPS（每秒 1 帧静态图）。
  - 批量自动化：集成 Tkinter GUI，三步极简工作流。
====================================================================

模块化说明（v4.1 拆分）：界面在 `ui/`，任务编排在 `pipeline.py`，媒体调用在
`ffmpeg.py` / `denoise.py` / `asr.py`，字幕生成在 `subtitle.py`，配置与路径在
`config.py`。版本号与 `config.APP_VERSION` 保持单一来源。
"""

from .config import APP_VERSION

__version__ = APP_VERSION

__all__ = ["__version__"]

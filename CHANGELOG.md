# Changelog

本文件记录本项目的所有重要变更。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 说明：`4.1` 及更早的条目由 `mp3tom4/__init__.py` 的包文档迁入，原始开发
> 日志未记录具体发布日期，故仅保留版本号与小标题。

## [5.0.0] - 2026-10-23

### Added
- 三语界面（简体中文 / 繁體中文 / English），支持运行时即时切换
- 单选音频 + 选项组合的执行模型：降噪、识别与字幕、视频生成三组独立可组合
- 独立降噪音频导出（48 kHz 立体声 WAV）
- 原声与降噪音轨可同时输出两个 MP4
- 自动化测试套件（pytest，111+ 用例）
- 模块化包结构（config / ffmpeg / denoise / asr / subtitle / pipeline / ui / i18n）

### Changed
- 界面由线性步骤流程改为分组选项 + 统一执行按钮
- GTCRN 降噪输出升采样至 48 kHz（日志提示高频损失）
- 下拉选项改为内部值与显示文案分离，配置不再受界面语言影响

### Fixed
- 处理过程异常导致界面永久卡在「处理中」
- 取消按钮无法终止 FFmpeg 子进程
- 降噪关闭后仍勾选降噪 MP4 导致静默跳过
- SRT 序号因空文本段而跳号
- 「重新检测」覆盖用户手动指定的 FFmpeg 路径
- 未知配置值导致识别被静默关闭
- 字幕文件重名时被静默覆盖

## [4.1] — 组合式任务版

### Changed
- 界面重构：三卡式布局改为「单输入 + 选项 A / 选项 B 组合勾选 + 一个执行按钮」
- 任务计划：降噪、字幕（SRT / TXT 独立勾选）、原声配图 MP4、降噪配图 MP4
  可任意组合；降噪音频一次生成、多处复用；只勾降噪选项时也能单独产出降噪音频
- 渲染：新增 48 kHz 双声道降噪音频成片路径（RNNoise 保留 48k / GTCRN 16k 处理后上采样）

### Fixed
- 健壮性：工作线程整体异常兜底、取消可真正终止 ffmpeg 子进程、产物统一防覆盖

## [4.0] — 语音识别 / 降噪字幕版

### Added
- 语音识别：集成 faster-whisper（CTranslate2 推理），音频/视频转写为文字，
  输出同名 `.srt` 字幕与 `.txt` 文本
- 混合语种：默认自动检测，中英混说无需手动切换；也可强制指定中文或英文
- 模型可选：large-v3-turbo（1.55 GB，默认，精度优先）/ medium / small（464 MB，
  速度快）/ base / tiny
- 前置降噪：RNNoise（ffmpeg arnndn，0.3 MB，零额外依赖）与 GTCRN 神经网络
  （sherpa-onnx，0.5 MB）两级可选。降噪只作用于「送去识别的音频」，
  成片 MP4 的音轨始终保持原始音质

### Changed
- 渲染逻辑不变：仍是 1 FPS 静态图 + AAC 192k，字幕以旁挂文件形式输出，
  方便 YouTube 单独上传

## [3.0] — FFmpeg 引擎版

### Added
- 引擎切换：由 MoviePy 改为直接调用 FFmpeg 子进程。速度更快、内存占用更低，
  且不再依赖 Python 媒体库
- 多格式支持：MP3 / M4A / AAC / WAV / FLAC / OGG / OPUS / WMA / AIFF / APE 等
  ffmpeg 可解的所有音频
- 封面适配：默认输出 1920x1080，等比缩放 + 黑边补齐；可切换
  「原图尺寸 / 1080p / 720p」
- YouTube 兼容：libx264 + yuv420p + faststart + AAC 192k，上传即可识别
- 体验增强：实时百分比进度、可中途取消、记住上次设置、同名输出自动加序号不覆盖

### Fixed
- 自动探测系统中的 ffmpeg（PATH / winget / 程序同目录 / 常见安装路径 /
  imageio-ffmpeg），并在启动失败时弹窗提示，不再「双击无反应」

## [2.1] — MoviePy 2.x 适配版

### Changed
- 语法重构：适配 MoviePy v2.0+ API，`set_duration` / `set_audio` 替换为
  `with_duration` / `with_audio`
- 核心引擎升级：直接从 `moviepy` 根目录引入核心类

## [1.0] — 极速渲染奠基版

### Added
- 架构确立：引入 MoviePy 作为调度引擎，底层隐式调用 FFmpeg 混流封装
- 核心算法优化：强制视频帧率 1 FPS（每秒 1 帧静态图）
- 批量自动化：集成 Tkinter GUI，三步极简工作流

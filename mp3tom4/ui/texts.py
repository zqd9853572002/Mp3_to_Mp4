# -*- coding: utf-8 -*-
"""界面文案集中存放。

本轮只做「把散布在 main_window 里的中文字符串搬到一处」，**不含任何 i18n 逻辑**，
文案内容与拆分前逐字一致。带花括号的是 `.format()` 模板。
"""

# ---------- 窗口 / 通用 ----------
WINDOW_TITLE = "{title} v{version}"
TXT_NOT_SELECTED = "未选择"
FILETYPE_ALL_FILES = "全部文件"

# ---------- FFmpeg 状态栏 ----------
LBL_ENGINE_PREFIX = "⚙ FFmpeg 引擎："
TXT_ENGINE_DETECTING = "检测中..."
TXT_ENGINE_NOT_FOUND = "未找到可用的 ffmpeg（点击右侧「更换」手动指定）"
BTN_ENGINE_CHANGE = "更换"
BTN_ENGINE_REDETECT = "重新检测"

# ---------- 分组标题 ----------
GROUP_INPUT = "输入音频"
GROUP_OPTIONS_A = "选项 A · 音频与文字"
GROUP_OPTIONS_B = "选项 B · 视频生成"
GROUP_OUTPUT = "输出目录"

# ---------- 输入音频 ----------
CAPTION_AUDIO = "音频"
BTN_SELECT_AUDIO = "选择音频"
TXT_AUDIO_SELECTED = "已选中 {count} 个音频"

# ---------- 选项 A · 音频与文字 ----------
CAPTION_DENOISE = "降噪"
CAPTION_MODEL = "识别模型"
CAPTION_LANG = "识别语种"
CAPTION_SUBTITLE = "生成字幕"
CHK_SRT = "SRT"
CHK_TXT = "TXT"

# ---------- 选项 B · 视频生成 ----------
CHK_MUX_ORIGINAL = "原始音频配图 MP4"
CHK_MUX_DENOISED = "降噪音频配图 MP4"
CAPTION_COVER = "封面"
BTN_SELECT_COVER = "选择封面"
CAPTION_SIZE = "输出尺寸"
LBL_SIZE_HINT = "（非 16:9 封面会等比缩放并补黑边）"

# ---------- 输出目录 ----------
CAPTION_OUTPUT_DIR = "输出目录"
BTN_SELECT_OUTPUT_DIR = "选择输出目录"

# ---------- 执行区 ----------
BTN_START = "▶ 开始执行"
BTN_START_BUSY = "⏳ 正在处理..."
BTN_CANCEL = "取消"

# ---------- 阶段文本 ----------
STAGE_READY = "就绪"
STAGE_CANCELLING = "正在取消..."
STAGE_CANCELLED = "已取消"
STAGE_DONE = "完成"
STAGE_READY_HINT = "就绪 · {count} 个音频 · {actions}"

# ---------- 校验提示 ----------
VALIDATE_NO_AUDIO = "请选择音频文件"
VALIDATE_NO_ACTION = "请至少选择一种处理方式"
VALIDATE_NEED_COVER = "已选视频输出，还需选择封面图片"

# ---------- 任务动作名 ----------
ACT_ONLY_DENOISE = "仅降噪音频"
ACT_SUBTITLE = "字幕"
ACT_MUX_ORIGINAL = "原声 MP4"
ACT_MUX_DENOISED = "降噪 MP4"

# ---------- 对话框：标题 / 提示 ----------
DLG_PICK_FFMPEG = "请选择 ffmpeg.exe"
DLG_FFMPEG_INVALID_TITLE = "不可用"
DLG_FFMPEG_INVALID_MSG = "无法执行该文件，请确认它是有效的 ffmpeg.exe。"
DLG_FFMPEG_MISSING_ENC_TITLE = "缺少编码器"
DLG_FFMPEG_MISSING_ENC_MSG = (
    "该 ffmpeg 缺少必要编码器（libx264={libx264}, aac={aac}），无法生成兼容 MP4。\n"
    "建议安装官方静态版：winget install --id Gyan.FFmpeg -e"
)
DLG_PICK_AUDIO = "请选择音频文件（可多选 / Ctrl+A 全选）"
DLG_PICK_COVER = "请选择一张封面图片"
DLG_PICK_OUTPUT_DIR = "请选择输出目录"
DLG_NO_FFMPEG_TITLE = "缺少 FFmpeg"
DLG_NO_FFMPEG_MSG = "未检测到可用的 ffmpeg，请先点击「更换」指定 ffmpeg.exe。"
DLG_MISSING_ASR_TITLE = "缺少语音识别依赖"
DLG_MISSING_ASR_MSG = (
    "未检测到 faster-whisper，无法生成字幕。\n\n请先安装一次依赖（约 200 MB）：\n\n"
    '"{exe}" -m pip install faster-whisper sherpa-onnx'
)

# ---------- 日志模板 ----------
LOG_WELCOME = ">>> 欢迎使用 {title} v{version}（FFmpeg 引擎 + 语音识别）。\n"
LOG_RENDER_INFO = ">>> 渲染逻辑：1 帧/秒，视频极小，音频保持原样重编码为 AAC 192k。\n"
LOG_FORMATS = ">>> 支持 {formats} 等格式。\n"
LOG_ASR_READY = ">>> 🎧 语音识别：faster-whisper 已就绪（首次使用会下载所选模型）。\n"
LOG_ASR_MISSING = (
    ">>> ⚠ 未安装 faster-whisper，字幕功能不可用。"
    "安装：python -m pip install faster-whisper sherpa-onnx\n"
)
LOG_DENOISE_READY = ">>> 🧹 降噪：RNNoise 与 GTCRN 均可使用。\n\n"
LOG_DENOISE_PARTIAL = ">>> 🧹 降噪：RNNoise 可用；GTCRN 需 python -m pip install sherpa-onnx。\n\n"
LOG_FFMPEG_ENABLED = ">>> ✅ 已启用 FFmpeg: {info}\n"
LOG_FFMPEG_SKIPPED = ">>> ⚠ 已跳过缺少 libx264/aac 的 ffmpeg: {dirs}\n"
LOG_FFMPEG_NONE = ">>> ❌ 未找到可用的 ffmpeg（需支持 libx264 与 aac）。\n"
LOG_FFMPEG_REJECTED_HEADER = ">>> 检测到但不可用的版本:\n"
LOG_FFMPEG_REJECTED_ITEM = "    - {path} (libx264={libx264}, aac={aac})\n"
LOG_FFMPEG_MANUAL = ">>> ✅ 已手动指定 FFmpeg: {path}\n"
LOG_AUDIO_IMPORTED = ">>> 已导入 {count} 个音频文件。\n"
LOG_OUTPUT_AUTO = ">>> 已自动设定输出目录为音频所在目录: {dir}\n"
LOG_OUTPUT_FALLBACK = ">>> 未指定输出目录，已回退到音频所在目录：{dir}\n"
LOG_COVER_READY = ">>> 封面图片已就绪: {name}\n"
LOG_OUTPUT_SET = ">>> 输出目录已设定为: {dir}\n"
LOG_TASK_HEADER = "=" * 64 + "\n"
LOG_OUTPUT_DIR = ">>> 📂 输出目录：{dir}\n"
LOG_DENOISE_MODEL_LINE = ">>> 🧹 降噪：{denoise} · 🎧 识别模型：{model}\n"
LOG_TASKS = ">>> 🧾 本次任务：{tasks}\n"
LOG_FIRST_MODEL = ">>> ⏬ 首次使用 {model}，需先下载模型权重，耗时取决于网速。\n"
LOG_START = ">>> 🚀 开始处理，共 {count} 个文件。\n\n"
LOG_CANCEL_REQUEST = ">>> 🛑 已请求取消，正在停止当前任务...\n"
TASK_SUBTITLE = "字幕({formats})"
TXT_MODEL_OFF = "关闭"

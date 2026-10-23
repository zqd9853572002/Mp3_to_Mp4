# -*- coding: utf-8 -*-
"""底层基础设施：常量、配置持久化、路径与轻量工具。

本模块是依赖图的最底层，**不导入本项目任何其他模块**。

`download_file` / `remove_file_quiet` 放在此处而不是单独的 util 模块，理由：
它们只依赖标准库与本模块的 `APP_NAME` / `APP_VERSION` 常量，且 `config` 已经
是「路径与模型目录」的唯一归属（`models_root()` 就在本模块）。再拆一个 util
模块只会多一层同级依赖，不会减少耦合。
"""

import importlib.util
import json
import os
import urllib.request
from pathlib import Path

APP_NAME = "Mp3ToMp4"
APP_VERSION = "4.1"
APP_TITLE = "极速音频转 MP4 批量引擎"

# 项目根目录（原单文件脚本所在目录）：用于探测随程序放置的 ffmpeg.exe。
# 原代码用 `Path(__file__).resolve().parent`，模块化后本文件位于 <根>/mp3tom4/，
# 因此取上一级，保证探测行为与拆分前完全一致。
PROJECT_ROOT = Path(__file__).resolve().parent.parent

AUDIO_EXTS = (
    ".mp3", ".m4a", ".m4b", ".aac", ".wav", ".flac", ".ogg", ".oga",
    ".opus", ".wma", ".aiff", ".aif", ".ape", ".wv", ".amr", ".ac3", ".dts",
)
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

AUDIO_FILETYPES = [
    ("全部支持的音频", " ".join("*" + e for e in AUDIO_EXTS)),
    ("全部文件", "*.*"),
]
IMAGE_FILETYPES = [
    ("图片文件", " ".join("*" + e for e in IMAGE_EXTS)),
    ("全部文件", "*.*"),
]

# ---------- 选项表：内部值 ↔ 显示文案 ----------
# 所有下拉框的「值」与「文案」在此分离：
#   * 配置文件、任务计划一律使用内部值（二元组左侧），跨版本稳定；
#   * 界面只渲染右侧文案，未来做多语言时只需替换文案列。
SIZE_OPTIONS = [
    ("1080p", "1080p (1920x1080)"),
    ("720p", "720p (1280x720)"),
    ("orig", "原图尺寸（仅偶数修正）"),
]
STT_MODEL_OPTIONS = [
    ("off", "关闭（不识别）"),
    ("large-v3-turbo", "large-v3-turbo（1.55 GB · 精度优先）"),
    ("medium", "medium（1.46 GB · 折中）"),
    ("small", "small（464 MB · 速度快）"),
    ("base", "base（141 MB · 轻量）"),
    ("tiny", "tiny（75 MB · 极速）"),
]
STT_LANG_OPTIONS = [
    ("auto", "自动检测（中英混合）"),
    ("zh", "中文"),
    ("en", "英文"),
]
DENOISE_OPTIONS = [
    ("off", "关闭"),
    ("arnndn", "轻度 · RNNoise（推荐）"),
    ("gtcrn", "强力 · GTCRN（神经网络）"),
]

SIZE_TARGETS = {"1080p": (1920, 1080), "720p": (1280, 720)}
DEFAULT_MODE = "1080p"

# ---------- 语音识别 / 降噪 ----------
STT_OFF = "off"
DEFAULT_STT_MODEL = "large-v3-turbo"
DEFAULT_STT_LANG = "auto"
DEFAULT_DENOISE = "arnndn"


def option_values(options):
    """选项表的全部内部值（按显示顺序）。"""
    return [value for value, _label in options]


def option_labels(options):
    """选项表的全部显示文案（按显示顺序）。"""
    return [label for _value, label in options]


def option_label(options, value, default_value=None):
    """内部值 → 显示文案。

    同时容忍直接传入旧版显示文案（旧配置迁移场景）。无法识别时使用
    `default_value` 对应的文案，缺省取该组第一项。
    """
    for val, label in options:
        if value == val or value == label:
            return label
    fallback = default_value if default_value is not None else options[0][0]
    for val, label in options:
        if val == fallback:
            return label
    return options[0][1]


def resolve_option(options, raw, default):
    """把配置/界面取到的值解析成内部值，返回 ``(内部值, 是否被识别)``。

    接受内部值，也接受旧版中文显示文案；无法识别时回退到 ``default``
    （明确指定的默认值，而不是该组第一项）。``raw`` 为空视为「未配置」，
    返回默认值且不视为异常。
    """
    if raw is None or raw == "":
        return default, True
    for value, label in options:
        if raw == value or raw == label:
            return value, True
    return default, False

RNNOISE_URL = "https://raw.githubusercontent.com/richardpl/arnndn-models/master/bd.rnnn"
GTCRN_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speech-enhancement-models/gtcrn_simple.onnx"
)


# ==================== 配置持久化 ====================
def config_file() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME / "config.json"


def load_config() -> dict:
    try:
        with open(config_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        path = config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def legacy_subtitle_flags(cfg: dict):
    """把旧配置（v4.0 只有 `stt_enabled`）折算成 (srt, txt) 两个开关。

    旧键语义为「同时生成两种格式」；显式写过的 `srt_enabled` / `txt_enabled`
    优先于旧键。
    """
    legacy_stt = cfg.get("stt_enabled")
    legacy_flag = bool(legacy_stt) if legacy_stt is not None else False
    return (
        bool(cfg.get("srt_enabled", legacy_flag)),
        bool(cfg.get("txt_enabled", legacy_flag)),
    )


# ==================== 路径 / 依赖 / 下载 ====================
def models_root() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME / "models"


def module_available(name: str) -> bool:
    """只检查模块是否存在，不真正导入（避免启动变慢）。"""
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def download_file(url: str, dest: Path, log=None, label: str = "") -> bool:
    """带 .part 临时文件的小文件下载，失败不抛异常。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        if log:
            log(f"    ⏬ 正在下载{label} {dest.name} …\n")
        req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        done = 0
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(1 << 18)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
        tmp.replace(dest)
        if log:
            log(f"    ✅ 已保存 {dest.name}（{done / 1048576:.2f} MB）\n")
        return True
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        if log:
            log(f"    ❌ 下载失败：{exc}\n", True)
        return False


def remove_file_quiet(path: str) -> None:
    """删除文件，失败也不抛异常。"""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

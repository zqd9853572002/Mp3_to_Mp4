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

SIZE_MODES = {
    "1080p (1920x1080)": "1080p",
    "720p (1280x720)": "720p",
    "原图尺寸（仅偶数修正）": "orig",
}
SIZE_TARGETS = {"1080p": (1920, 1080), "720p": (1280, 720)}
DEFAULT_MODE = "1080p"

# ---------- 语音识别 / 降噪 ----------
STT_OFF = "off"
STT_MODELS = {
    "关闭（不识别）": STT_OFF,
    "large-v3-turbo（1.55 GB · 精度优先）": "large-v3-turbo",
    "medium（1.46 GB · 折中）": "medium",
    "small（464 MB · 速度快）": "small",
    "base（141 MB · 轻量）": "base",
    "tiny（75 MB · 极速）": "tiny",
}
STT_LANGS = {
    "自动检测（中英混合）": "auto",
    "中文": "zh",
    "英文": "en",
}
DENOISE_MODES = {
    "关闭": "off",
    "轻度 · RNNoise（推荐）": "arnndn",
    "强力 · GTCRN（神经网络）": "gtcrn",
}
DEFAULT_STT_MODEL = "large-v3-turbo"
DEFAULT_STT_LANG = "auto"
DEFAULT_DENOISE = "arnndn"

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

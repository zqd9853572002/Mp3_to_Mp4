# -*- coding: utf-8 -*-
"""底层基础设施：常量、配置持久化、路径与轻量工具。

本模块是依赖图的最底层：只依赖标准库与 `i18n` 词条层，**不导入 ffmpeg /
denoise / pipeline / ui**。`i18n` 读取配置时采用函数内延迟导入，因此这里的
顶层 `from .i18n import t` 不会形成循环导入。

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

from .i18n import t, text_for

APP_NAME = "Mp3ToMp4"
APP_VERSION = "4.1"

# 项目根目录（原单文件脚本所在目录）：用于探测随程序放置的 ffmpeg.exe。
# 原代码用 `Path(__file__).resolve().parent`，模块化后本文件位于 <根>/mp3tom4/，
# 因此取上一级，保证探测行为与拆分前完全一致。
PROJECT_ROOT = Path(__file__).resolve().parent.parent

AUDIO_EXTS = (
    ".mp3", ".m4a", ".m4b", ".aac", ".wav", ".flac", ".ogg", ".oga",
    ".opus", ".wma", ".aiff", ".aif", ".ape", ".wv", ".amr", ".ac3", ".dts",
)
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

# 注意：文件对话框的过滤器文案依赖当前界面语言，已移到 UI 层
# （`ui.main_window.audio_filetypes()` / `image_filetypes()`），
# 本模块只保留与语言无关的扩展名常量。

# ---------- 选项表：内部值 ↔ 文案词条 key ----------
# 所有下拉框的「值」与「文案」在此分离：
#   * 配置文件、任务计划一律使用内部值（二元组左侧），跨版本稳定；
#   * 二元组右侧是 `mp3tom4/locale/*.json` 的词条 key，由 `option_label()`
#     在渲染时翻译，因此切换语言后重新渲染下拉框即可，不触碰内部值。
SIZE_OPTIONS = [
    ("1080p", "opt.size.1080p"),
    ("720p", "opt.size.720p"),
    ("orig", "opt.size.orig"),
]
STT_MODEL_OPTIONS = [
    ("off", "opt.model.off"),
    ("large-v3-turbo", "opt.model.large-v3-turbo"),
    ("medium", "opt.model.medium"),
    ("small", "opt.model.small"),
    ("base", "opt.model.base"),
    ("tiny", "opt.model.tiny"),
]
STT_LANG_OPTIONS = [
    ("auto", "opt.lang.auto"),
    ("zh", "opt.lang.zh"),
    ("en", "opt.lang.en"),
]
DENOISE_OPTIONS = [
    ("off", "opt.denoise.off"),
    ("arnndn", "opt.denoise.arnndn"),
    ("gtcrn", "opt.denoise.gtcrn"),
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


def _render_label(label_or_key):
    """词条 key → 当前语言文案；非 `opt.` 前缀视为已翻译好的字面量。"""
    return t(label_or_key) if label_or_key.startswith("opt.") else label_or_key


def _label_variants(label_or_key):
    """同一选项在各语言下的全部显示文案（用于旧配置反查）。"""
    if not label_or_key.startswith("opt."):
        return {label_or_key}
    variants = {label_or_key, t(label_or_key)}
    for code in ("zh_CN", "zh_TW", "en"):
        # 旧版配置里一定存的是 zh_CN 文案，必须始终可识别
        text = text_for(code, label_or_key)
        if text:
            variants.add(text)
    return variants


def option_labels(options):
    """选项表的全部显示文案（按当前界面语言）。"""
    return [_render_label(label) for _value, label in options]


def option_label(options, value, default_value=None):
    """内部值 → 当前语言的显示文案。

    同时容忍直接传入某一语言的显示文案（旧配置迁移场景）。无法识别时使用
    `default_value` 对应的文案，缺省取该组第一项。
    """
    for val, label in options:
        if value == val:
            return _render_label(label)
    for val, label in options:
        if value in _label_variants(label):
            return _render_label(label)
    fallback = default_value if default_value is not None else options[0][0]
    for val, label in options:
        if val == fallback:
            return _render_label(label)
    return _render_label(options[0][1])


def resolve_option(options, raw, default):
    """把配置/界面取到的值解析成内部值，返回 ``(内部值, 是否被识别)``。

    接受内部值，也接受**当前语言**或**旧版中文**显示文案；无法识别时回退到
    ``default``（明确指定的默认值，而不是该组第一项）。``raw`` 为空视为
    「未配置」，返回默认值且不视为异常。
    """
    if raw is None or raw == "":
        return default, True
    for value, label in options:
        if raw == value or raw == label:
            return value, True
    for value, label in options:
        if raw in _label_variants(label):
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
            log(t("log.download_start", label=label, name=dest.name))
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
            log(t("log.download_done", name=dest.name, size=done / 1048576))
        return True
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        if log:
            log(t("log.download_failed", exc=exc), True)
        return False


def remove_file_quiet(path: str) -> None:
    """删除文件，失败也不抛异常。"""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

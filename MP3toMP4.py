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
"""

import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

# 🛑 隐藏 Windows 黑窗口（异常由 main() 统一弹窗提示）
if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception:
        pass

APP_NAME = "Mp3ToMp4"
APP_VERSION = "4.1"
APP_TITLE = "极速音频转 MP4 批量引擎"

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

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


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


# ==================== ffmpeg 探测 ====================
def run_quiet(args, timeout=30):
    """静默执行命令，永不抛异常。"""
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            errors="replace", creationflags=NO_WINDOW,
        )
    except Exception:
        return None


def ffmpeg_info(path: str):
    """返回 ffmpeg 的版本与编码器能力；无效路径返回 None。"""
    if not path or not os.path.isfile(path):
        return None
    ver = run_quiet([path, "-hide_banner", "-version"], timeout=20)
    if not ver or ver.returncode != 0:
        return None
    text = (ver.stdout or "") + (ver.stderr or "")
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    enc = run_quiet([path, "-hide_banner", "-encoders"], timeout=20)
    enc_text = ((enc.stdout or "") + (enc.stderr or "")) if enc else ""
    return {
        "path": path,
        "version": first,
        "libx264": "libx264" in enc_text,
        "aac": re.search(r"\baac\b", enc_text) is not None,
    }


def ffmpeg_candidates(saved=None):
    """按优先级生成候选 ffmpeg 路径。"""
    found = []

    def add(p):
        if p and p not in found:
            found.append(p)

    add(saved)
    here = Path(__file__).resolve().parent
    add(str(here / "ffmpeg.exe"))
    add(str(here / "bin" / "ffmpeg.exe"))
    add(shutil.which("ffmpeg"))

    local = os.environ.get("LOCALAPPDATA", "")
    patterns = [
        os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
        os.path.join(local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin", "ffmpeg.exe"),
        os.path.join(local, "Microsoft", "WinGet", "Packages", "BtbN.FFmpeg*", "**", "bin", "ffmpeg.exe"),
        os.path.join(local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "**", "bin", "ffmpeg.exe"),
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Files\Software\ffmpeg\bin\ffmpeg.exe",
        r"C:\Files\Software\FormatFactory\ffmpeg.exe",
        os.path.join(local, "JianyingPro", "Apps", "*", "ffmpeg.exe"),
    ]
    for pattern in patterns:
        try:
            for hit in sorted(glob.glob(pattern, recursive=True), reverse=True):
                add(hit)
        except Exception:
            pass

    try:  # 可选依赖：装了 imageio-ffmpeg 也能用
        import imageio_ffmpeg

        add(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    return found


def discover_ffmpeg(saved=None):
    """返回 (可用的 ffmpeg 信息列表, 不可用但存在的列表)。"""
    usable, rejected = [], []
    for path in ffmpeg_candidates(saved):
        info = ffmpeg_info(path)
        if not info:
            continue
        (usable if (info["libx264"] and info["aac"]) else rejected).append(info)
    return usable, rejected


def probe_duration(ffmpeg: str, audio_path: str) -> float:
    """用 ffmpeg -i 的输出解析音频时长（秒）。"""
    res = run_quiet([ffmpeg, "-hide_banner", "-i", audio_path], timeout=30)
    text = ((res.stdout or "") + (res.stderr or "")) if res else ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def build_video_filter(mode: str) -> str:
    """构造缩放/补边滤镜，保证输出宽高为偶数，并统一为 yuv420p(tv)。

    JPEG 封面的输入是 full-range（yuvj420p），不显式 format 会在输出里保留
    full-range 标记，导致播放器/YouTube 上出现色彩偏移，因此这里强制转换。
    """
    if mode == "orig":
        return "scale=trunc(iw/2)*2:trunc(ih/2)*2:out_range=tv,format=yuv420p"
    width, height = SIZE_TARGETS[mode]
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:out_range=tv,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
        f"format=yuv420p"
    )


def unique_path(path: str) -> str:
    """同名文件已存在时自动追加序号，避免覆盖。"""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    index = 1
    while True:
        candidate = f"{stem} ({index}){ext}"
        if not os.path.exists(candidate):
            return candidate
        index += 1


def convert_one(ffmpeg, audio_path, image_path, out_path, mode, duration, on_progress, should_stop,
                on_proc=None):
    """执行单个转换，返回 (returncode, stderr 文本)。

    on_proc 为可选回调：子进程启动时回调 Popen 句柄、结束时回调 None，
    让 GUI 的取消按钮可以直接 terminate 真正的 ffmpeg 进程。
    """
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", "1", "-i", image_path,
        "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", build_video_filter(mode),
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-r", "1",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-shortest",
        "-progress", "pipe:1", "-nostats",
        out_path,
    ]
    err_file = tempfile.TemporaryFile(mode="w+b")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=err_file,
        creationflags=NO_WINDOW, universal_newlines=True, bufsize=1,
    )
    if on_proc is not None:
        on_proc(proc)
    try:
        for line in proc.stdout:
            if should_stop():
                proc.terminate()
                break
            line = line.strip()
            if line.startswith("out_time_us="):
                value = line.split("=", 1)[1]
                if value.isdigit() and duration > 0:
                    on_progress(min(99.0, int(value) / 1_000_000.0 / duration * 100.0))
        proc.wait()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        if on_proc is not None:
            on_proc(None)

    err_file.seek(0)
    err_text = err_file.read().decode("utf-8", "replace").strip()
    err_file.close()
    return proc.returncode, err_text


def run_ffmpeg_stream(cmd, duration, should_stop, on_progress=None, on_proc=None):
    """执行 ffmpeg 命令并解析 -progress 输出，返回 (returncode, stderr 文本)。"""
    err_file = tempfile.TemporaryFile(mode="w+b")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=err_file,
        creationflags=NO_WINDOW, universal_newlines=True, bufsize=1,
    )
    if on_proc is not None:
        on_proc(proc)
    try:
        for line in proc.stdout:
            if should_stop():
                proc.terminate()
                break
            line = line.strip()
            if line.startswith("out_time_us=") and on_progress and duration > 0:
                value = line.split("=", 1)[1]
                if value.lstrip("-").isdigit():
                    on_progress(min(99.0, int(value) / 1_000_000.0 / duration * 100.0))
        proc.wait()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        if on_proc is not None:
            on_proc(None)

    err_file.seek(0)
    err_text = err_file.read().decode("utf-8", "replace").strip()
    err_file.close()
    return proc.returncode, err_text


# ==================== 语音识别 / 降噪 ====================
_WHISPER_CACHE = {}
_DENOISER_CACHE = {}


def module_available(name: str) -> bool:
    """只检查模块是否存在，不真正导入（避免启动变慢）。"""
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def models_root() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME / "models"


def whisper_model_ready(model_name: str) -> bool:
    """判断 HuggingFace 缓存里是否已有该模型的权重。"""
    root = models_root() / "whisper"
    if not root.is_dir():
        return False
    for repo in root.glob("models--*"):
        if repo.name.endswith(model_name) and any(repo.rglob("model.bin")):
            return True
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


def ensure_denoise_model(mode: str, log=None) -> str:
    """确保降噪模型就位，返回本地路径；失败返回空串。"""
    cache = models_root() / "denoise"
    if mode == "arnndn":
        dest = cache / "bd.rnnn"
        if dest.is_file() and dest.stat().st_size > 100_000:
            return str(dest)
        return str(dest) if download_file(RNNOISE_URL, dest, log, "RNNoise 模型") else ""
    if mode == "gtcrn":
        dest = cache / "gtcrn_simple.onnx"
        if dest.is_file() and dest.stat().st_size > 400_000:
            return str(dest)
        return str(dest) if download_file(GTCRN_URL, dest, log, "GTCRN 模型") else ""
    return ""


def filter_escape_path(path: str) -> str:
    """FFmpeg 滤镜参数里的 Windows 路径需要转义盘符冒号。"""
    return path.replace("\\", "/").replace(":", "\\:")


def decode_to_wav(ffmpeg: str, src: str, dst: str, audio_filter: str = ""):
    """用 ffmpeg 解码为 16kHz 单声道 PCM WAV，返回 (ok, 错误文本)。"""
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    if audio_filter:
        cmd += ["-af", audio_filter]
    cmd += ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", dst]
    res = run_quiet(cmd, timeout=3600)
    if res is None:
        return False, "ffmpeg 无法启动"
    if res.returncode != 0:
        return False, (res.stderr or res.stdout or "ffmpeg 解码失败")
    return True, ""


def read_wav_float32(path: str):
    """读取 PCM WAV 为 numpy float32 单声道（-1.0 ~ 1.0）。"""
    import wave

    import numpy as np

    with wave.open(path, "rb") as w:
        frames = w.getnframes()
        channels = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(frames)
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype("float32") / 2147483648.0
    else:
        data = np.frombuffer(raw, dtype=np.uint8).astype("float32") / 128.0 - 1.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def write_wav_s16(path: str, samples, rate: int) -> None:
    """把 float32 波形写成 16bit PCM WAV。"""
    import wave

    import numpy as np

    arr = np.clip(np.asarray(samples, dtype="float32"), -1.0, 1.0)
    pcm = (arr * 32767.0).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm)


def _run_gtcrn(base_wav: str, out_wav: str, model_path: str, log=None) -> bool:
    """用 sherpa-onnx 的 GTCRN 模型做神经网络降噪。"""
    try:
        import sherpa_onnx

        denoiser = _DENOISER_CACHE.get(model_path)
        if denoiser is None:
            cfg = sherpa_onnx.OfflineSpeechDenoiserConfig(
                model=sherpa_onnx.OfflineSpeechDenoiserModelConfig(
                    gtcrn=sherpa_onnx.OfflineSpeechDenoiserGtcrnModelConfig(model=model_path),
                    num_threads=max(1, min(4, os.cpu_count() or 2)),
                    provider="cpu",
                    debug=False,
                )
            )
            denoiser = sherpa_onnx.OfflineSpeechDenoiser(cfg)
            _DENOISER_CACHE[model_path] = denoiser
        samples, rate = read_wav_float32(base_wav)
        audio = denoiser.run(samples, int(rate))
        write_wav_s16(out_wav, audio.samples, int(audio.sample_rate))
        return True
    except Exception as exc:
        if log:
            log(f"    ⚠ GTCRN 降噪失败：{exc}\n", True)
        return False


def prepare_asr_audio(ffmpeg: str, src: str, mode: str, workdir: str, log=None) -> str:
    """统一用 FFmpeg 解码成 Whisper 需要的 16k 单声道 WAV，可先降噪。

    这样做同时规避了 faster-whisper 内置 PyAV 解码与新版 av 接口不兼容的问题。
    返回 WAV 路径；失败返回空串。
    """
    out_wav = os.path.join(workdir, "asr_input.wav")

    if mode == "arnndn":
        model_path = ensure_denoise_model("arnndn", log)
        chain = "highpass=f=80"
        if model_path:
            chain += (
                ",aresample=48000,arnndn=m='"
                + filter_escape_path(model_path)
                + "',aresample=16000"
            )
        else:
            chain += ",aresample=16000"
        ok, err = decode_to_wav(ffmpeg, src, out_wav, chain)
        if not ok:
            if log:
                log(f"    ⚠ RNNoise 降噪失败：{err.strip()[:200]}\n", True)
            return ""
        return out_wav

    if mode == "gtcrn":
        # 依赖缺失时自动退回 RNNoise，保证任务不中断
        model_path = ensure_denoise_model("gtcrn", log)
        if not model_path or not module_available("sherpa_onnx"):
            if log:
                log("    ⚠ 缺少 sherpa-onnx 或 GTCRN 模型，已自动回退 RNNoise。\n", True)
            return prepare_asr_audio(ffmpeg, src, "arnndn", workdir, log)
        base_wav = os.path.join(workdir, "decoded.wav")
        ok, err = decode_to_wav(ffmpeg, src, base_wav)
        if not ok:
            if log:
                log(f"    ⚠ 音频解码失败：{err.strip()[:200]}\n", True)
            return ""
        return out_wav if _run_gtcrn(base_wav, out_wav, model_path, log) else ""

    # 不降噪：仅解码为 16k 单声道 WAV
    ok, err = decode_to_wav(ffmpeg, src, out_wav)
    if not ok:
        if log:
            log(f"    ⚠ 音频解码失败：{err.strip()[:200]}\n", True)
        return ""
    return out_wav


# ==================== 任务计划 ====================
@dataclass
class JobPlan:
    """主线程读取完所有 Tk 变量后打包出的纯数据任务计划。

    工作线程只读这份快照，绝不再触碰任何 *_var，避免跨线程访问 Tk 对象。
    """
    audio_files: list
    output_dir: str
    image_path: str
    size_mode: str
    model_name: str | None
    language: str | None
    denoise_mode: str | None
    srt: bool
    txt: bool
    mux_original: bool
    mux_denoised: bool
    need_stt: bool
    need_denoise: bool
    only_denoise: bool


def remove_file_quiet(path: str) -> None:
    """删除文件，失败也不抛异常。"""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def render_denoised_audio(ffmpeg, src, out_wav, mode, should_stop, log,
                          progress_cb=None, on_proc=None) -> bool:
    """把源音频降噪后渲染成 48kHz / 双声道 / 16bit WAV（成片专用）。

    与 prepare_asr_audio 的关键区别：这里不做 16000Hz 单声道降采样，
    成片音轨必须保留高频，否则听感会明显发闷。
    """
    if not mode or mode == "off":
        return False

    duration = probe_duration(ffmpeg, src)
    tmp_out = str(Path(out_wav).with_suffix(".part.wav"))

    def report(pct):
        if progress_cb:
            progress_cb(max(0.0, min(100.0, pct)))

    def finish(code, err):
        if code != 0 or not os.path.isfile(tmp_out):
            remove_file_quiet(tmp_out)
            if code != 0 and log and err:
                last = [ln for ln in err.splitlines() if ln.strip()]
                log(f"    ⚠ 降噪失败：{(last[-1] if last else '未知错误')[:200]}\n", True)
            return False
        try:
            os.replace(tmp_out, out_wav)
        except Exception as exc:
            remove_file_quiet(tmp_out)
            if log:
                log(f"    ⚠ 降噪结果写入失败：{exc}\n", True)
            return False
        report(100.0)
        return True

    if mode == "gtcrn":
        model_path = ensure_denoise_model("gtcrn", log)
        if not model_path or not module_available("sherpa_onnx"):
            if log:
                log("    ⚠ 缺少 sherpa-onnx 或 GTCRN 模型，已自动回退 RNNoise。\n", True)
            return render_denoised_audio(ffmpeg, src, out_wav, "arnndn",
                                         should_stop, log, progress_cb, on_proc)
        workdir = tempfile.mkdtemp(prefix="mp3tomp4_denoise_")
        try:
            if log:
                log("    ℹ 强力降噪按 16k 单声道处理后再上采样到 48kHz，高频会有损失。\n")
            base_wav = os.path.join(workdir, "decoded.wav")
            ok, err = decode_to_wav(ffmpeg, src, base_wav)
            if not ok:
                if log:
                    log(f"    ⚠ 音频解码失败：{err.strip()[:200]}\n", True)
                return False
            if should_stop():
                return False
            report(30.0)

            den_wav = os.path.join(workdir, "denoised.wav")
            if not _run_gtcrn(base_wav, den_wav, model_path, log):
                if log:
                    log("    ⚠ GTCRN 处理失败，已自动回退 RNNoise。\n", True)
                return render_denoised_audio(ffmpeg, src, out_wav, "arnndn",
                                             should_stop, log, progress_cb, on_proc)
            report(60.0)
            if should_stop():
                return False

            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", den_wav,
                "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
                "-progress", "pipe:1", "-nostats", tmp_out,
            ]
            rc, err = run_ffmpeg_stream(
                cmd, duration, should_stop, lambda p: report(60.0 + p * 0.4), on_proc)
            if should_stop():
                remove_file_quiet(tmp_out)
                return False
            return finish(rc, err)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # 轻度：RNNoise，滤镜链保留 48kHz（末尾不再 aresample 到 16k）
    model_path = ensure_denoise_model("arnndn", log)
    chain = "highpass=f=80"
    if model_path:
        chain += ",aresample=48000,arnndn=m='" + filter_escape_path(model_path) + "'"
    elif log:
        log("    ⚠ RNNoise 模型不可用，本次仅做高通滤波。\n", True)
    chain += ",aresample=48000"

    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
        "-af", chain, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
        "-progress", "pipe:1", "-nostats", tmp_out,
    ]
    rc, err = run_ffmpeg_stream(cmd, duration, should_stop, report, on_proc)
    if should_stop():
        remove_file_quiet(tmp_out)
        return False
    return finish(rc, err)


def get_whisper_model(model_name: str, log=None):
    """加载并缓存 Whisper 模型（同一时间只保留一个，避免内存叠加）。"""
    model = _WHISPER_CACHE.get(model_name)
    if model is not None:
        return model
    from faster_whisper import WhisperModel

    for key in list(_WHISPER_CACHE):
        if key != model_name:
            _WHISPER_CACHE.pop(key, None)

    root = str(models_root() / "whisper")
    os.makedirs(root, exist_ok=True)
    if not whisper_model_ready(model_name) and log:
        log("    ⏬ 首次使用该模型，正在下载权重（大文件，请耐心等待）…\n")
        log("       如下载缓慢，可设置环境变量 HF_ENDPOINT=https://hf-mirror.com 后重试。\n")
    model = WhisperModel(model_name, device="cpu", compute_type="int8", download_root=root)
    _WHISPER_CACHE[model_name] = model
    if log:
        log("    ✅ 识别模型已加载。\n")
    return model


def transcribe_audio(audio_path: str, model_name: str, language, duration: float,
                     on_progress, should_stop, log=None):
    """转写 16k 单声道 WAV，返回 (segments, info)。segments 为 [{start, end, text}]。"""
    model = get_whisper_model(model_name, log)
    samples, rate = read_wav_float32(audio_path)
    if int(rate) != 16000:
        raise ValueError(f"输入音频采样率必须为 16kHz，当前为 {rate}Hz")
    # 直接传 numpy 数组，绕开 faster-whisper 内置的 PyAV 解码路径
    segments, info = model.transcribe(
        samples,
        language=language,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400, "speech_pad_ms": 200},
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        word_timestamps=False,
    )
    result = []
    for seg in segments:
        if should_stop():
            break
        text = (seg.text or "").strip()
        if text:
            result.append({"start": float(seg.start), "end": float(seg.end), "text": text})
        if duration > 0 and on_progress:
            on_progress(min(99.0, max(0.0, float(seg.end) / duration * 100.0)))
    if on_progress:
        on_progress(99.0 if result else 0.0)
    return result, info


def format_timestamp(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    hours, rem = divmod(total_ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def char_width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(text: str) -> int:
    return sum(char_width(ch) for ch in text)


def wrap_subtitle(text: str, limit: int = 42, max_lines: int = 3):
    """按显示宽度折行：中文占 2 宽度，英文占 1，优先在空格处断开。"""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    if display_width(text) <= limit:
        return [text]
    lines, current, width = [], [], 0
    for ch in text:
        w = char_width(ch)
        if width + w > limit and current:
            line = "".join(current)
            if " " in line:
                head, tail = line.rsplit(" ", 1)
                if head.strip() and tail:
                    lines.append(head.strip())
                    current = list(tail)
                    width = display_width(tail)
                    if ch != " ":
                        current.append(ch)
                        width += w
                    continue
            lines.append(line.strip())
            current = [] if ch == " " else [ch]
            width = 0 if ch == " " else w
        else:
            current.append(ch)
            width += w
    if current:
        lines.append("".join(current).strip())
    return [ln for ln in lines if ln][:max_lines]


def write_srt(segments, path: str) -> None:
    blocks = []
    for index, seg in enumerate(segments, start=1):
        start = max(0.0, seg["start"])
        end = max(start + 0.2, seg["end"])
        lines = wrap_subtitle(seg["text"])
        if not lines:
            continue
        blocks.append(str(index))
        blocks.append(f"{format_timestamp(start)} --> {format_timestamp(end)}")
        blocks.extend(lines)
        blocks.append("")
    Path(path).write_text("\n".join(blocks) + "\n", encoding="utf-8")


def _is_cjk(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def write_txt(segments, path: str) -> None:
    parts = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if parts and not (_is_cjk(parts[-1][-1]) or _is_cjk(text[0])):
            parts.append(" ")
        parts.append(text)
    Path(path).write_text("".join(parts) + "\n", encoding="utf-8")


# ==================== GUI ====================
class AudioToVideoApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("980x940")
        self.root.minsize(960, 900)
        self.root.configure(bg="#1E1E1E")

        self.cfg = load_config()
        self.audio_files = []
        self.image_path = ""
        self.output_dir = ""
        self.ffmpeg_path = ""
        self.ffmpeg_text = ""
        self._proc = None
        self._stop = False
        self._busy = False

        # 旧配置（v4.0）只有一个 stt_enabled：等于「同时生成两种格式」
        legacy_stt = self.cfg.get("stt_enabled")
        legacy_flag = bool(legacy_stt) if legacy_stt is not None else False

        self.size_var = tk.StringVar(value=self._label_from_mode(self.cfg.get("size_mode", DEFAULT_MODE)))
        self.progress_var = tk.DoubleVar(value=0.0)
        self.stage_var = tk.StringVar(value="就绪")

        self.stt_model_var = tk.StringVar(value=self._label_from_value(
            STT_MODELS, self.cfg.get("stt_model", DEFAULT_STT_MODEL)))
        self.stt_lang_var = tk.StringVar(value=self._label_from_value(
            STT_LANGS, self.cfg.get("stt_language", DEFAULT_STT_LANG)))
        self.denoise_var = tk.StringVar(value=self._label_from_value(
            DENOISE_MODES, self.cfg.get("denoise_mode", DEFAULT_DENOISE)))
        self.srt_var = tk.BooleanVar(value=bool(self.cfg.get("srt_enabled", legacy_flag)))
        self.txt_var = tk.BooleanVar(value=bool(self.cfg.get("txt_enabled", legacy_flag)))
        self.mux_original_var = tk.BooleanVar(value=bool(self.cfg.get("mux_original", False)))
        self.mux_denoised_var = tk.BooleanVar(value=bool(self.cfg.get("mux_denoised", False)))

        self.setup_ui()
        self._restore_saved_selection()
        self.root.after(100, self.refresh_ffmpeg)

    # ---------- 配置辅助 ----------
    @staticmethod
    def _label_from_mode(mode: str) -> str:
        for label, value in SIZE_MODES.items():
            if value == mode:
                return label
        return next(k for k, v in SIZE_MODES.items() if v == DEFAULT_MODE)

    @staticmethod
    def _label_from_value(mapping: dict, value) -> str:
        for label, val in mapping.items():
            if val == value:
                return label
        return next(iter(mapping))

    def _persist(self):
        self.cfg.update({
            "ffmpeg_path": self.ffmpeg_path,
            "image_path": self.image_path,
            "output_dir": self.output_dir,
            "size_mode": SIZE_MODES.get(self.size_var.get(), DEFAULT_MODE),
            "stt_model": STT_MODELS.get(self.stt_model_var.get(), DEFAULT_STT_MODEL),
            "stt_language": STT_LANGS.get(self.stt_lang_var.get(), DEFAULT_STT_LANG),
            "denoise_mode": DENOISE_MODES.get(self.denoise_var.get(), DEFAULT_DENOISE),
            "srt_enabled": bool(self.srt_var.get()),
            "txt_enabled": bool(self.txt_var.get()),
            "mux_original": bool(self.mux_original_var.get()),
            "mux_denoised": bool(self.mux_denoised_var.get()),
        })
        # 旧键已完成迁移，不再写回，避免与 srt/txt 两份开关冲突
        self.cfg.pop("stt_enabled", None)
        save_config(self.cfg)

    def _on_option_change(self, *_args):
        """下拉/复选框统一入口：先落盘，再刷新联动状态。"""
        self._persist()
        self._sync_options()

    # ---------- 联动置灰 ----------
    def _option_flags(self):
        """把界面选项折算成「本次要做什么」的布尔组合（不触碰工作线程）。"""
        model_code = STT_MODELS.get(self.stt_model_var.get(), DEFAULT_STT_MODEL)
        denoise_code = DENOISE_MODES.get(self.denoise_var.get(), DEFAULT_DENOISE)
        denoise_on = denoise_code != "off"
        srt = bool(self.srt_var.get())
        txt = bool(self.txt_var.get())
        mux_original = bool(self.mux_original_var.get())
        mux_denoised = bool(self.mux_denoised_var.get()) and denoise_on
        need_stt = (model_code != STT_OFF) and (srt or txt)
        only_denoise = denoise_on and not need_stt and not mux_original and not mux_denoised
        return {
            "stt_on": model_code != STT_OFF,
            "denoise_on": denoise_on,
            "need_stt": need_stt,
            "mux_original": mux_original,
            "mux_denoised": mux_denoised,
            "only_denoise": only_denoise,
        }

    def _validate_plan(self):
        """返回 (是否可执行, 中性阶段提示)。"""
        flags = self._option_flags()
        if not self.audio_files:
            return False, "请选择音频文件"
        if not (flags["need_stt"] or flags["mux_original"]
                or flags["mux_denoised"] or flags["only_denoise"]):
            return False, "请至少选择一种处理方式"
        if (flags["mux_original"] or flags["mux_denoised"]) and not self.image_path:
            return False, "已选视频输出，还需选择封面图片"
        acts = []
        if flags["only_denoise"]:
            acts.append("仅降噪音频")
        if flags["need_stt"]:
            acts.append("字幕")
        if flags["mux_original"]:
            acts.append("原声 MP4")
        if flags["mux_denoised"]:
            acts.append("降噪 MP4")
        return True, f"就绪 · {len(self.audio_files)} 个音频 · " + " + ".join(acts)

    def _sync_options(self, *_args):
        """根据当前选项刷新控件的可用性，并决定主按钮是否可点。"""
        if self._busy:
            self.btn_start.config(state=tk.DISABLED)
            return

        flags = self._option_flags()

        # 识别模型 = 关闭 → 语种与字幕格式一并置灰（但不主动清空勾选）
        if flags["stt_on"]:
            self.cmb_lang.config(state="readonly")
            self.chk_srt.config(state=tk.NORMAL)
            self.chk_txt.config(state=tk.NORMAL)
        else:
            self.cmb_lang.config(state=tk.DISABLED)
            self.chk_srt.config(state=tk.DISABLED)
            self.chk_txt.config(state=tk.DISABLED)

        # 降噪 = 关闭 → 降噪 MP4 置灰（保留原勾选，恢复时自动还原）
        self.chk_mux_denoised.config(
            state=tk.NORMAL if flags["denoise_on"] else tk.DISABLED)

        # 封面按钮：没有视频输出时灰色但仍可点击，方便提前准备素材
        if flags["mux_original"] or flags["mux_denoised"]:
            self.btn_img.config(bg="#D97706", fg="white", activebackground="#B45309",
                                activeforeground="white", cursor="hand2")
        else:
            self.btn_img.config(bg="#4A4A4A", fg="#9A9A9A", activebackground="#4A4A4A",
                                activeforeground="#9A9A9A", cursor="hand2")

        ok, hint = self._validate_plan()
        self.btn_start.config(state=tk.NORMAL if ok else tk.DISABLED)
        self.stage_var.set(hint)

    def _restore_saved_selection(self):
        saved_image = self.cfg.get("image_path", "")
        if saved_image and os.path.isfile(saved_image):
            self.image_path = saved_image
            self.lbl_img.config(text=os.path.basename(saved_image), fg="#4AF626")
        saved_out = self.cfg.get("output_dir", "")
        if saved_out and os.path.isdir(saved_out):
            self.output_dir = saved_out
            self.lbl_dir.config(text=saved_out, fg="#4AF626")
        self._sync_options()

    # ---------- 界面 ----------
    def _group(self, title):
        """带边框的分组容器，返回可放行的内层 Frame。"""
        outer = tk.Frame(self.root, bg="#252526", highlightbackground="#3C3C3C",
                         highlightthickness=1)
        outer.pack(fill="x", padx=20, pady=(0, 8))
        inner = tk.Frame(outer, bg="#252526")
        inner.pack(fill="x", padx=10, pady=8)
        tk.Label(inner, text=title, bg="#252526", fg="#9CDCFE", anchor="w",
                 font=("Microsoft YaHei", 9, "bold")).pack(fill="x", pady=(0, 4))
        return inner

    @staticmethod
    def _row(parent):
        row = tk.Frame(parent, bg="#252526")
        row.pack(fill="x", pady=2)
        return row

    @staticmethod
    def _caption(parent, text):
        return tk.Label(parent, text=text, bg="#252526", fg="#CCCCCC", width=9,
                        anchor="w", font=("Microsoft YaHei", 9))

    def setup_ui(self):
        # --- FFmpeg 状态栏 ---
        engine_frame = tk.Frame(self.root, bg="#252526", pady=8)
        engine_frame.pack(fill="x", padx=0, pady=(0, 4))

        tk.Label(engine_frame, text="⚙ FFmpeg 引擎：", bg="#252526", fg="#CCCCCC",
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left", padx=(20, 0))
        self.lbl_engine = tk.Label(engine_frame, text="检测中...", bg="#252526", fg="#A9A9A9",
                                   font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_engine.pack(side="left", fill="x", expand=True, padx=8)

        self.btn_engine = tk.Button(engine_frame, text="更换", font=("Microsoft YaHei", 9),
                                    bg="#3C3C3C", fg="white", relief="flat", width=6,
                                    command=self.choose_ffmpeg)
        self.btn_engine.pack(side="right", padx=(0, 6))
        self.btn_redetect = tk.Button(engine_frame, text="重新检测", font=("Microsoft YaHei", 9),
                                      bg="#3C3C3C", fg="white", relief="flat", width=9,
                                      command=self.refresh_ffmpeg)
        self.btn_redetect.pack(side="right", padx=(0, 6))

        # --- 输入音频 ---
        grp_in = self._group("输入音频")
        row = self._row(grp_in)
        self._caption(row, "音频").pack(side="left")
        self.btn_audio = tk.Button(row, text="选择音频", font=("Microsoft YaHei", 9, "bold"),
                                   bg="#007ACC", fg="white", activebackground="#005A9E",
                                   activeforeground="white", width=14, relief="flat",
                                   command=self.select_audio)
        self.btn_audio.pack(side="left")
        self.lbl_audio = tk.Label(row, text="未选择", bg="#252526", fg="#A9A9A9",
                                  font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_audio.pack(side="left", padx=12)

        # --- 选项 A · 音频与文字 ---
        grp_a = self._group("选项 A · 音频与文字")
        row = self._row(grp_a)
        self._caption(row, "降噪").pack(side="left")
        self.cmb_denoise = ttk.Combobox(row, textvariable=self.denoise_var, state="readonly",
                                        values=list(DENOISE_MODES.keys()), width=22,
                                        font=("Microsoft YaHei", 9))
        self.cmb_denoise.pack(side="left")
        self.cmb_denoise.bind("<<ComboboxSelected>>", self._on_option_change)

        row = self._row(grp_a)
        self._caption(row, "识别模型").pack(side="left")
        self.cmb_model = ttk.Combobox(row, textvariable=self.stt_model_var, state="readonly",
                                      values=list(STT_MODELS.keys()), width=30,
                                      font=("Microsoft YaHei", 9))
        self.cmb_model.pack(side="left", padx=(0, 18))
        self.cmb_model.bind("<<ComboboxSelected>>", self._on_option_change)
        self._caption(row, "识别语种").pack(side="left")
        self.cmb_lang = ttk.Combobox(row, textvariable=self.stt_lang_var, state="readonly",
                                     values=list(STT_LANGS.keys()), width=16,
                                     font=("Microsoft YaHei", 9))
        self.cmb_lang.pack(side="left")
        self.cmb_lang.bind("<<ComboboxSelected>>", self._on_option_change)

        row = self._row(grp_a)
        self._caption(row, "生成字幕").pack(side="left")
        self.chk_srt = tk.Checkbutton(row, text="SRT", variable=self.srt_var,
                                      command=self._on_option_change, bg="#252526",
                                      fg="#CCCCCC", selectcolor="#2D2D30",
                                      activebackground="#252526", activeforeground="white",
                                      font=("Microsoft YaHei", 9), anchor="w")
        self.chk_srt.pack(side="left")
        self.chk_txt = tk.Checkbutton(row, text="TXT", variable=self.txt_var,
                                      command=self._on_option_change, bg="#252526",
                                      fg="#CCCCCC", selectcolor="#2D2D30",
                                      activebackground="#252526", activeforeground="white",
                                      font=("Microsoft YaHei", 9), anchor="w")
        self.chk_txt.pack(side="left", padx=(16, 0))

        # --- 选项 B · 视频生成 ---
        grp_b = self._group("选项 B · 视频生成")
        row = self._row(grp_b)
        self.chk_mux_original = tk.Checkbutton(
            row, text="原始音频配图 MP4", variable=self.mux_original_var,
            command=self._on_option_change, bg="#252526", fg="#CCCCCC",
            selectcolor="#2D2D30", activebackground="#252526", activeforeground="white",
            font=("Microsoft YaHei", 9), anchor="w")
        self.chk_mux_original.pack(side="left")

        row = self._row(grp_b)
        self.chk_mux_denoised = tk.Checkbutton(
            row, text="降噪音频配图 MP4", variable=self.mux_denoised_var,
            command=self._on_option_change, bg="#252526", fg="#CCCCCC",
            selectcolor="#2D2D30", activebackground="#252526", activeforeground="white",
            font=("Microsoft YaHei", 9), anchor="w")
        self.chk_mux_denoised.pack(side="left")

        row = self._row(grp_b)
        self._caption(row, "封面").pack(side="left")
        self.btn_img = tk.Button(row, text="选择封面", font=("Microsoft YaHei", 9, "bold"),
                                 bg="#D97706", fg="white", activebackground="#B45309",
                                 activeforeground="white", width=14, relief="flat",
                                 command=self.select_image)
        self.btn_img.pack(side="left")
        self.lbl_img = tk.Label(row, text="未选择", bg="#252526", fg="#A9A9A9",
                                font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_img.pack(side="left", padx=12)

        row = self._row(grp_b)
        self._caption(row, "输出尺寸").pack(side="left")
        self.cmb_size = ttk.Combobox(row, textvariable=self.size_var, state="readonly",
                                     values=list(SIZE_MODES.keys()), width=24,
                                     font=("Microsoft YaHei", 9))
        self.cmb_size.pack(side="left")
        self.cmb_size.bind("<<ComboboxSelected>>", self._on_option_change)
        tk.Label(row, text="（非 16:9 封面会等比缩放并补黑边）", bg="#252526", fg="#777777",
                 font=("Microsoft YaHei", 8)).pack(side="left", padx=10)

        # --- 输出目录 ---
        grp_out = self._group("输出目录")
        row = self._row(grp_out)
        self._caption(row, "输出目录").pack(side="left")
        self.btn_dir = tk.Button(row, text="选择输出目录", font=("Microsoft YaHei", 9, "bold"),
                                 bg="#8B5CF6", fg="white", activebackground="#7C3AED",
                                 activeforeground="white", width=14, relief="flat",
                                 command=self.select_directory)
        self.btn_dir.pack(side="left")
        self.lbl_dir = tk.Label(row, text="未选择", bg="#252526", fg="#A9A9A9",
                                font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_dir.pack(side="left", padx=12)

        # --- 执行区 ---
        exec_row = tk.Frame(self.root, bg="#1E1E1E")
        exec_row.pack(fill="x", padx=20, pady=(0, 6))
        self.btn_start = tk.Button(exec_row, text="▶ 开始执行", font=("Microsoft YaHei", 10, "bold"),
                                   bg="#10B981", fg="white", activebackground="#059669",
                                   activeforeground="white", disabledforeground="#9CA3AF",
                                   relief="flat", width=22, height=2, cursor="hand2",
                                   command=self.start_processing)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.btn_cancel = tk.Button(exec_row, text="取消", font=("Microsoft YaHei", 10, "bold"),
                                    bg="#B91C1C", fg="white", activebackground="#991B1B",
                                    activeforeground="white", disabledforeground="#9CA3AF",
                                    relief="flat", width=8, height=2,
                                    state=tk.DISABLED, command=self.cancel_processing)
        self.btn_cancel.pack(side="left")

        style = ttk.Style(self.root)
        try:
            style.theme_use("default")
        except Exception:
            pass
        style.configure("Zoo.Horizontal.TProgressbar", troughcolor="#2D2D30",
                        background="#10B981", thickness=14)
        self.progress = ttk.Progressbar(self.root, variable=self.progress_var, maximum=100.0,
                                        style="Zoo.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=20, pady=(0, 2))
        tk.Label(self.root, textvariable=self.stage_var, bg="#1E1E1E", fg="#A9A9A9",
                 font=("Microsoft YaHei", 9), anchor="w").pack(fill="x", padx=20)

        # --- 日志区 ---
        self.text_area = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, font=("Consolas", 10),
                                                   bg="#0C0C0C", fg="#4AF626", padx=10, pady=10,
                                                   borderwidth=0, height=10)
        self.text_area.pack(fill="both", expand=True, padx=20, pady=(4, 16))
        self.text_area.tag_config("error", foreground="#FF4500")
        self.text_area.tag_config("info", foreground="#5CB3FF")

        self.log(f">>> 欢迎使用 {APP_TITLE} v{APP_VERSION}（FFmpeg 引擎 + 语音识别）。\n")
        self.log(">>> 渲染逻辑：1 帧/秒，视频极小，音频保持原样重编码为 AAC 192k。\n")
        self.log(">>> 支持 " + " / ".join(e.lstrip(".").upper() for e in AUDIO_EXTS[:10]) + " 等格式。\n")
        if module_available("faster_whisper"):
            self.log(">>> 🎧 语音识别：faster-whisper 已就绪（首次使用会下载所选模型）。\n")
        else:
            self.log(">>> ⚠ 未安装 faster-whisper，字幕功能不可用。"
                     "安装：python -m pip install faster-whisper sherpa-onnx\n", is_error=True)
        if module_available("sherpa_onnx"):
            self.log(">>> 🧹 降噪：RNNoise 与 GTCRN 均可使用。\n\n")
        else:
            self.log(">>> 🧹 降噪：RNNoise 可用；GTCRN 需 python -m pip install sherpa-onnx。\n\n")
        self._sync_options()

    # ---------- 日志 / 进度 ----------
    def log(self, text, is_error=False):
        self.root.after(0, self._insert_text, text, is_error)

    def _insert_text(self, text, is_error):
        self.text_area.insert(tk.END, text, "error" if is_error else "normal")
        self.text_area.see(tk.END)

    def set_progress(self, value):
        self.root.after(0, lambda: self.progress_var.set(max(0.0, min(100.0, value))))

    def set_stage(self, text):
        self.root.after(0, lambda: self.stage_var.set(text))

    # ---------- 引擎 ----------
    def refresh_ffmpeg(self):
        saved = self.cfg.get("ffmpeg_path")
        usable, rejected = discover_ffmpeg(saved)
        if usable:
            best = usable[0]
            self.ffmpeg_path = best["path"]
            ver = best["version"].replace("ffmpeg version", "").strip()
            short = ver.split("Copyright")[0].strip()[:60]
            self.ffmpeg_text = f"{best['path']}  ({short})"
            self.lbl_engine.config(text=self.ffmpeg_text, fg="#4AF626")
            self.log(f">>> ✅ 已启用 FFmpeg: {self.ffmpeg_text}\n")
            if rejected:
                self.log(">>> ⚠ 已跳过缺少 libx264/aac 的 ffmpeg: " +
                         "; ".join(os.path.dirname(r["path"]) for r in rejected) + "\n")
            self._persist_path_only()
        else:
            self.ffmpeg_path = ""
            self.lbl_engine.config(text="未找到可用的 ffmpeg（点击右侧「更换」手动指定）", fg="#FF4500")
            self.log(">>> ❌ 未找到可用的 ffmpeg（需支持 libx264 与 aac）。\n", is_error=True)
            if rejected:
                self.log(">>> 检测到但不可用的版本:\n", is_error=True)
                for r in rejected:
                    self.log(f"    - {r['path']} (libx264={r['libx264']}, aac={r['aac']})\n", is_error=True)

    def _persist_path_only(self):
        if self.ffmpeg_path and self.cfg.get("ffmpeg_path") != self.ffmpeg_path:
            self.cfg["ffmpeg_path"] = self.ffmpeg_path
            save_config(self.cfg)

    def choose_ffmpeg(self):
        path = filedialog.askopenfilename(title="请选择 ffmpeg.exe", filetypes=[("ffmpeg", "ffmpeg.exe"), ("全部文件", "*.*")])
        if not path:
            return
        info = ffmpeg_info(path)
        if not info:
            messagebox.showerror("不可用", "无法执行该文件，请确认它是有效的 ffmpeg.exe。")
            return
        if not (info["libx264"] and info["aac"]):
            messagebox.showerror(
                "缺少编码器",
                f"该 ffmpeg 缺少必要编码器（libx264={info['libx264']}, aac={info['aac']}），无法生成兼容 MP4。\n"
                "建议安装官方静态版：winget install --id Gyan.FFmpeg -e",
            )
            return
        self.ffmpeg_path = path
        self.ffmpeg_text = f"{path}  ({info['version'].split('Copyright')[0].strip()[:60]})"
        self.lbl_engine.config(text=self.ffmpeg_text, fg="#4AF626")
        self._persist_path_only()
        self.log(f">>> ✅ 已手动指定 FFmpeg: {path}\n")

    # ---------- 选择文件 ----------
    def select_audio(self):
        files = filedialog.askopenfilenames(
            title="请选择音频文件（可多选 / Ctrl+A 全选）", filetypes=AUDIO_FILETYPES)
        if not files:
            return
        self.audio_files = list(files)
        self.lbl_audio.config(text=f"已选中 {len(self.audio_files)} 个音频", fg="#4AF626")
        self.log(f">>> 已导入 {len(self.audio_files)} 个音频文件。\n")
        if not self.output_dir:
            first_dir = os.path.dirname(self.audio_files[0])
            self.output_dir = first_dir
            self.lbl_dir.config(text=first_dir, fg="#4AF626")
            self.log(f">>> 已自动设定输出目录为音频所在目录: {first_dir}\n")
        self._persist()
        self._sync_options()

    def select_image(self):
        path = filedialog.askopenfilename(title="请选择一张封面图片", filetypes=IMAGE_FILETYPES)
        if not path:
            return
        self.image_path = path
        self.lbl_img.config(text=os.path.basename(path), fg="#4AF626")
        self.log(f">>> 封面图片已就绪: {os.path.basename(path)}\n")
        self._persist()
        self._sync_options()

    def select_directory(self):
        directory = filedialog.askdirectory(title="请选择输出目录")
        if not directory:
            return
        self.output_dir = directory
        self.lbl_dir.config(text=directory, fg="#4AF626")
        self.log(f">>> 输出目录已设定为: {directory}\n")
        self._persist()
        self._sync_options()

    # ---------- 执行 ----------
    def lock_ui(self, locked: bool):
        self._busy = locked
        state = tk.DISABLED if locked else tk.NORMAL
        for widget in (self.btn_audio, self.btn_img, self.btn_dir,
                       self.btn_engine, self.btn_redetect):
            widget.config(state=state)
        for widget in (self.chk_srt, self.chk_txt,
                       self.chk_mux_original, self.chk_mux_denoised):
            widget.config(state=state)
        combo_state = tk.DISABLED if locked else "readonly"
        for widget in (self.cmb_model, self.cmb_lang, self.cmb_denoise, self.cmb_size):
            widget.config(state=combo_state)

        if locked:
            self.btn_start.config(state=tk.DISABLED, text="⏳ 正在处理...")
            self.btn_cancel.config(state=tk.NORMAL)
        else:
            self.btn_start.config(text="▶ 开始执行")
            self.btn_cancel.config(state=tk.DISABLED)
            self._sync_options()

    @staticmethod
    def _denoise_desc(mode):
        if not mode:
            return "关闭"
        return {v: k for k, v in DENOISE_MODES.items()}.get(mode, mode)

    def _build_plan(self):
        """在主线程一次性读完全部 Tk 变量，打包成 JobPlan 交给工作线程。"""
        model_code = STT_MODELS.get(self.stt_model_var.get(), DEFAULT_STT_MODEL)
        model_name = None if model_code == STT_OFF else model_code
        denoise_code = DENOISE_MODES.get(self.denoise_var.get(), DEFAULT_DENOISE)
        denoise_mode = None if denoise_code == "off" else denoise_code
        lang_code = STT_LANGS.get(self.stt_lang_var.get(), DEFAULT_STT_LANG)
        language = None if lang_code == "auto" else lang_code

        srt = bool(self.srt_var.get())
        txt = bool(self.txt_var.get())
        mux_original = bool(self.mux_original_var.get())
        mux_denoised = bool(self.mux_denoised_var.get()) and denoise_mode is not None

        need_stt = (model_name is not None) and (srt or txt)
        only_denoise = (denoise_mode is not None) and not need_stt \
            and not mux_original and not mux_denoised
        need_denoise = (denoise_mode is not None) and (
            need_stt or mux_denoised or only_denoise)

        return JobPlan(
            audio_files=list(self.audio_files),
            output_dir=self.output_dir,
            image_path=self.image_path,
            size_mode=SIZE_MODES.get(self.size_var.get(), DEFAULT_MODE),
            model_name=model_name,
            language=language,
            denoise_mode=denoise_mode,
            srt=srt,
            txt=txt,
            mux_original=mux_original,
            mux_denoised=mux_denoised,
            need_stt=need_stt,
            need_denoise=need_denoise,
            only_denoise=only_denoise,
        )

    def start_processing(self):
        if not self.ffmpeg_path:
            messagebox.showwarning("缺少 FFmpeg", "未检测到可用的 ffmpeg，请先点击「更换」指定 ffmpeg.exe。")
            self.choose_ffmpeg()
            return

        ok, hint = self._validate_plan()
        if not ok:
            self.stage_var.set(hint)
            return

        # 未指定输出目录时回退到第一个音频所在目录（沿用旧行为）
        if not self.output_dir:
            self.output_dir = os.path.dirname(self.audio_files[0])
            self.lbl_dir.config(text=self.output_dir, fg="#4AF626")
            self.log(f">>> 未指定输出目录，已回退到音频所在目录：{self.output_dir}\n")

        plan = self._build_plan()
        if plan.need_stt and not module_available("faster_whisper"):
            messagebox.showerror(
                "缺少语音识别依赖",
                "未检测到 faster-whisper，无法生成字幕。\n\n请先安装一次依赖（约 200 MB）：\n\n"
                f'"{sys.executable}" -m pip install faster-whisper sherpa-onnx',
            )
            return

        self._stop = False
        self._proc = None
        self.progress_var.set(0)
        self.lock_ui(True)

        tasks = []
        if plan.only_denoise:
            tasks.append("仅降噪音频")
        if plan.need_stt:
            formats = " / ".join(
                [name for name, on in (("SRT", plan.srt), ("TXT", plan.txt)) if on])
            tasks.append(f"字幕({formats})")
        if plan.mux_original:
            tasks.append("原声配图 MP4")
        if plan.mux_denoised:
            tasks.append("降噪配图 MP4")

        self.log("=" * 64 + "\n")
        self.log(f">>> 📂 输出目录：{plan.output_dir}\n")
        self.log(f">>> 🧹 降噪：{self._denoise_desc(plan.denoise_mode)} · "
                 f"🎧 识别模型：{plan.model_name or '关闭'}\n")
        self.log(f">>> 🧾 本次任务：{' + '.join(tasks)}\n")
        if plan.need_stt and not whisper_model_ready(plan.model_name):
            self.log(f">>> ⏬ 首次使用 {plan.model_name}，需先下载模型权重，耗时取决于网速。\n")
        self.log(f">>> 🚀 开始处理，共 {len(plan.audio_files)} 个文件。\n\n")
        threading.Thread(target=self._worker, args=(plan,), daemon=True).start()

    def cancel_processing(self):
        self._stop = True
        self.set_stage("正在取消...")
        self.log(">>> 🛑 已请求取消，正在停止当前任务...\n", is_error=True)
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _set_proc(self, proc):
        """ffmpeg 子进程句柄回调，取消按钮据此真正 terminate。"""
        self._proc = proc

    # ---------- 工作线程 ----------
    def _build_steps(self, plan):
        """按实际需要的步骤动态分配 0-100 的进度区间。"""
        raw = []
        if plan.need_denoise:
            raw.append(("降噪", 30))
        if plan.need_stt:
            raw.append(("语音识别", 40))
        if plan.mux_original:
            raw.append(("封装原声视频", 30))
        if plan.mux_denoised:
            raw.append(("封装降噪视频", 30))
        total_weight = sum(weight for _, weight in raw) or 1
        steps, cursor = [], 0.0
        for name, weight in raw:
            span = weight * 100.0 / total_weight
            steps.append((name, cursor, cursor + span))
            cursor += span
        return steps

    def _do_stt(self, plan, asr_src, stem, duration, p_start, p_end):
        """语音识别并按勾选写出 SRT / TXT；失败不影响后续步骤。"""
        workdir = tempfile.mkdtemp(prefix="mp3tomp4_asr_")
        started = time.time()
        try:
            lang_text = plan.language or "自动检测"
            self.log(f"  🎧 识别中（{plan.model_name} · {lang_text}）...\n")
            # 降噪音频是 48k 成片音轨，这里统一重新解码成 ASR 需要的 16k 单声道
            asr_input = prepare_asr_audio(
                self.ffmpeg_path, asr_src, "off", workdir, self.log)
            if not asr_input:
                self.log("  ⚠ 音频预处理失败，跳过字幕生成。\n", is_error=True)
                return False
            if self._stop:
                return False

            segments, info = transcribe_audio(
                asr_input, plan.model_name, plan.language, duration,
                on_progress=lambda p: self.set_progress(
                    p_start + (p_end - p_start) * p / 100.0),
                should_stop=lambda: self._stop,
                log=self.log,
            )
            if self._stop:
                return False
            if not segments:
                self.log("  ⚠ 未识别到有效语音，未生成字幕。\n", is_error=True)
                return False

            produced = []
            if plan.srt:
                srt_path = unique_path(os.path.join(plan.output_dir, f"{stem}.srt"))
                write_srt(segments, srt_path)
                produced.append(os.path.basename(srt_path))
            if plan.txt:
                txt_path = unique_path(os.path.join(plan.output_dir, f"{stem}.txt"))
                write_txt(segments, txt_path)
                produced.append(os.path.basename(txt_path))

            lang_name = getattr(info, "language", "?")
            try:
                prob = float(getattr(info, "language_probability", 0.0) or 0.0)
            except Exception:
                prob = 0.0
            self.log(
                f"  ✅ 字幕已生成：{len(segments)} 条 · 语种 {lang_name} ({prob:.0%}) · "
                f"耗时 {time.time() - started:.0f}s\n"
                f"     → {' / '.join(produced) if produced else '（未勾选格式）'}\n"
            )
            return True
        except Exception as exc:
            self.log(f"  ❌ 语音识别失败：{exc}\n", is_error=True)
            return False
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _mux_one(self, plan, audio_src, out_path, duration, p_start, p_end):
        """封面 + 音频封装 MP4；取消或失败时删除半成品。"""
        self.log(f"  🎬 封装视频：{os.path.basename(out_path)}\n")
        rc, err = convert_one(
            self.ffmpeg_path, audio_src, plan.image_path, out_path, plan.size_mode, duration,
            on_progress=lambda p: self.set_progress(
                p_start + (p_end - p_start) * p / 100.0),
            should_stop=lambda: self._stop,
            on_proc=self._set_proc,
        )
        if self._stop:
            remove_file_quiet(out_path)
            self.log("  🛑 已取消，删除未完成的输出文件。\n", is_error=True)
            return False
        if rc == 0 and os.path.exists(out_path):
            size_mb = os.path.getsize(out_path) / 1048576.0
            self.log(f"  ✅ 成功：{os.path.basename(out_path)}（{size_mb:.2f} MB）\n")
            return True
        detail = (err or "未知错误").splitlines()
        detail_text = " | ".join(detail[-3:]) if detail else "未知错误"
        self.log(f"  ❌ 视频封装失败：{detail_text[:400]}\n", is_error=True)
        remove_file_quiet(out_path)
        return False

    def _worker(self, plan):
        total = len(plan.audio_files)
        steps = self._build_steps(plan)
        success = failed = completed = 0
        try:
            for index, audio_path in enumerate(plan.audio_files, start=1):
                if self._stop:
                    break
                base_name = os.path.basename(audio_path)
                stem = os.path.splitext(base_name)[0]
                self.set_progress(0)
                self.log(f"[{index}/{total}] {base_name}\n")

                duration = 0.0
                if plan.need_stt or plan.mux_original or plan.mux_denoised:
                    duration = probe_duration(self.ffmpeg_path, audio_path)
                    if duration <= 0:
                        self.log("  ⚠ 无法读取时长，进度条将不准确（不影响输出）。\n")

                denoised_audio = ""
                file_failed = False
                cancelled = False

                for step_index, (step_name, p_start, p_end) in enumerate(steps, start=1):
                    if self._stop:
                        cancelled = True
                        break
                    self.set_stage(
                        f"第 {index}/{total} 个 · {base_name} · "
                        f"正在{step_name}（{step_index}/{len(steps)}）")

                    if step_name == "降噪":
                        out_wav = unique_path(
                            os.path.join(plan.output_dir, f"{stem}_denoised.wav"))
                        self.log(f"  🧹 降噪中（{self._denoise_desc(plan.denoise_mode)}）...\n")
                        ok = render_denoised_audio(
                            self.ffmpeg_path, audio_path, out_wav, plan.denoise_mode,
                            should_stop=lambda: self._stop,
                            log=self.log,
                            progress_cb=lambda p, a=p_start, b=p_end: self.set_progress(
                                a + (b - a) * p / 100.0),
                            on_proc=self._set_proc,
                        )
                        if not ok:
                            if self._stop:
                                cancelled = True
                            else:
                                self.log("  ❌ 降噪失败，跳过该文件。\n", is_error=True)
                                file_failed = True
                            break
                        denoised_audio = out_wav
                        self.log(f"  ✅ 降噪音频：{os.path.basename(out_wav)}\n")

                    elif step_name == "语音识别":
                        if not self._do_stt(plan, denoised_audio or audio_path,
                                            stem, duration, p_start, p_end) and self._stop:
                            cancelled = True
                            break

                    else:
                        if step_name == "封装降噪视频":
                            src_audio, suffix = denoised_audio, "_denoised"
                        else:
                            src_audio, suffix = audio_path, ""
                        if not src_audio:
                            self.log("  ⚠ 缺少降噪音频，跳过降噪视频。\n", is_error=True)
                            continue
                        out_path = unique_path(
                            os.path.join(plan.output_dir, f"{stem}{suffix}.mp4"))
                        if not self._mux_one(plan, src_audio, out_path,
                                             duration, p_start, p_end):
                            if self._stop:
                                cancelled = True
                                break
                            file_failed = True
                            break

                    self.set_progress(p_end)

                if cancelled:
                    self.log("  🛑 已取消当前文件，跳过剩余任务。\n", is_error=True)
                    break
                if file_failed:
                    failed += 1
                else:
                    success += 1
                    completed += 1
                self.set_progress(100)
        except Exception:
            import traceback

            summary = "\n".join(traceback.format_exc().strip().splitlines()[-6:])
            self.log(f">>> ❌ 任务异常终止：\n{summary}\n", is_error=True)
        finally:
            self._proc = None
            self.log("\n" + "=" * 64 + "\n")
            if self._stop:
                self.log(f">>> 🛑 任务已取消：已完成 {completed}/{total} 个文件。\n",
                         is_error=True)
            else:
                self.log(f">>> 🎉 批量任务完成：成功 {success} 个，失败 {failed} 个。\n")
                self.log(f">>> 📂 输出目录：{plan.output_dir}\n")
                self.log(">>> 💡 下一步：打开 YouTube Studio 批量上传即可。\n")
            self.root.after(0, self._finish_ui)

    def _finish_ui(self):
        self.lock_ui(False)
        self.stage_var.set("已取消" if self._stop else "完成")


def main():
    try:
        root = tk.Tk()
    except Exception:
        import traceback

        print(traceback.format_exc())
        return

    def report_exception(exc, value, tb):
        import traceback

        detail = "".join(traceback.format_exception(exc, value, tb))
        try:
            messagebox.showerror("程序异常", detail[-1500:])
        except Exception:
            print(detail)

    root.report_callback_exception = report_exception
    AudioToVideoApp(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        trace = traceback.format_exc()
        print(trace)
        try:
            fallback = tk.Tk()
            fallback.withdraw()
            messagebox.showerror("启动失败", trace[-1500:])
            fallback.destroy()
        except Exception:
            pass

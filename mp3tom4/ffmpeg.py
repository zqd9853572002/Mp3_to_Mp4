# -*- coding: utf-8 -*-
"""FFmpeg 探测、时长解析、滤镜构造、封装与流式调用。

只允许依赖 `config`。
"""

import glob
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import PROJECT_ROOT, SIZE_TARGETS

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


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
    here = PROJECT_ROOT
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


def filter_escape_path(path: str) -> str:
    """FFmpeg 滤镜参数里的 Windows 路径需要转义盘符冒号。"""
    return path.replace("\\", "/").replace(":", "\\:")


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

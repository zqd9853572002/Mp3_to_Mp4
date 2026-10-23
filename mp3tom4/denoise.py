# -*- coding: utf-8 -*-
"""降噪模型管理、音频解码、RNNoise / GTCRN 降噪与降噪音轨渲染。

允许依赖 `config`、`ffmpeg`。
"""

import os
import shutil
import tempfile
from pathlib import Path

from .config import (
    GTCRN_URL,
    RNNOISE_URL,
    download_file,
    models_root,
    module_available,
    remove_file_quiet,
)
from .ffmpeg import (
    filter_escape_path,
    probe_duration,
    run_ffmpeg_stream,
    run_quiet,
)

_DENOISER_CACHE = {}


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

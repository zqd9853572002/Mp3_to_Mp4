# -*- coding: utf-8 -*-
"""Whisper 模型管理与语音识别。

允许依赖 `config`、`denoise`（转写链路需要读取 16k 单声道 WAV）。
"""

import os

from .config import models_root
from .denoise import read_wav_float32

_WHISPER_CACHE = {}


def whisper_model_ready(model_name: str) -> bool:
    """判断 HuggingFace 缓存里是否已有该模型的权重。"""
    root = models_root() / "whisper"
    if not root.is_dir():
        return False
    for repo in root.glob("models--*"):
        if repo.name.endswith(model_name) and any(repo.rglob("model.bin")):
            return True
    return False


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

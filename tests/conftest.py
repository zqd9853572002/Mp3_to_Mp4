# -*- coding: utf-8 -*-
"""pytest 公共 fixture：ffmpeg 可用性、测试音频素材、封面图片路径。"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mp3tom4 import ffmpeg as ffmpeg_mod  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: 调用真实 ffmpeg 的集成用例")


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True,
                          creationflags=ffmpeg_mod.NO_WINDOW)


@pytest.fixture(scope="session")
def ffmpeg_path():
    """优先使用同时具备 libx264 与 aac 的 ffmpeg；找不到则整组用例 skip。"""
    usable, _rejected = ffmpeg_mod.discover_ffmpeg()
    if not usable:
        pytest.skip("ffmpeg 不可用")
    return usable[0]["path"]


@pytest.fixture(scope="session")
def black_png():
    path = REPO_ROOT / "Black.png"
    if not path.is_file():
        pytest.skip("Black.png 缺失")
    return str(path)


@pytest.fixture()
def sine_audio(ffmpeg_path, tmp_path):
    """3 秒 440Hz 正弦波测试音频；mp3 编码不可用时退回 wav。"""
    mp3 = tmp_path / "sine.mp3"
    res = _run([ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                "-c:a", "libmp3lame", "-q:a", "4", str(mp3)])
    if res.returncode == 0 and mp3.is_file() and mp3.stat().st_size > 0:
        return str(mp3)

    wav = tmp_path / "sine.wav"
    res = _run([ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(wav)])
    if res.returncode != 0 or not wav.is_file():
        pytest.skip("无法生成测试音频")
    return str(wav)


@pytest.fixture()
def denoise_model(monkeypatch):
    """RNNoise 模型已存在则用真模型；不存在时屏蔽下载，避免测试联网。"""
    from mp3tom4 import config, denoise

    path = config.models_root() / "denoise" / "bd.rnnn"
    if path.is_file() and path.stat().st_size > 100_000:
        return str(path)
    monkeypatch.setattr(denoise, "ensure_denoise_model", lambda mode, log=None: "")
    return ""

# -*- coding: utf-8 -*-
"""config 模块：常量完整性、配置读写 round-trip、旧配置键兼容。"""

import json

from mp3tom4 import config


def test_constants_complete():
    assert config.APP_NAME == "Mp3ToMp4"
    assert config.APP_VERSION
    assert config.APP_TITLE

    assert config.AUDIO_EXTS
    assert all(ext.startswith(".") for ext in config.AUDIO_EXTS)
    assert ".mp3" in config.AUDIO_EXTS
    assert ".wav" in config.AUDIO_EXTS
    assert config.IMAGE_EXTS
    assert all(ext.startswith(".") for ext in config.IMAGE_EXTS)

    assert config.AUDIO_FILETYPES[0][0] == "全部支持的音频"
    assert "*" in config.AUDIO_FILETYPES[0][1]
    assert config.AUDIO_FILETYPES[-1] == ("全部文件", "*.*")
    assert config.IMAGE_FILETYPES[0][0] == "图片文件"
    assert config.IMAGE_FILETYPES[-1] == ("全部文件", "*.*")

    assert config.DEFAULT_MODE == "1080p"
    assert config.DEFAULT_MODE in config.SIZE_TARGETS
    assert set(config.SIZE_MODES.values()) == {"1080p", "720p", "orig"}
    assert config.SIZE_TARGETS["1080p"] == (1920, 1080)
    assert config.SIZE_TARGETS["720p"] == (1280, 720)

    assert config.STT_OFF == "off"
    assert config.STT_MODELS["关闭（不识别）"] == config.STT_OFF
    assert config.DEFAULT_STT_MODEL in config.STT_MODELS.values()
    assert config.DEFAULT_STT_LANG in config.STT_LANGS.values()
    assert config.DEFAULT_DENOISE == "arnndn"
    assert config.DENOISE_MODES["关闭"] == "off"
    assert config.DEFAULT_DENOISE in config.DENOISE_MODES.values()


def test_config_paths_keep_appdata_layout(monkeypatch, tmp_path):
    """%APPDATA%\\Mp3ToMp4\\config.json 与 ...\\models 路径必须原样保留。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config.config_file() == tmp_path / "Mp3ToMp4" / "config.json"
    assert config.models_root() == tmp_path / "Mp3ToMp4" / "models"


def test_config_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config.load_config() == {}

    data = {
        "size_mode": "720p",
        "stt_model": "tiny",
        "srt_enabled": True,
        "txt_enabled": False,
        "mux_original": True,
        "备注": "中文内容",
    }
    config.save_config(data)

    raw = config.config_file().read_text(encoding="utf-8")
    assert json.loads(raw) == data
    assert "中文内容" in raw, "配置必须保持 ensure_ascii=False 的中文可读性"
    assert config.load_config() == data


def test_load_config_tolerates_broken_json(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = config.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text("{not json", encoding="utf-8")
    assert config.load_config() == {}

    path.write_text("[]", encoding="utf-8")
    assert config.load_config() == {}


def test_legacy_stt_enabled_maps_to_srt_and_txt():
    assert config.legacy_subtitle_flags({}) == (False, False)
    assert config.legacy_subtitle_flags({"stt_enabled": True}) == (True, True)
    assert config.legacy_subtitle_flags({"stt_enabled": False}) == (False, False)
    # 新键优先于旧键
    assert config.legacy_subtitle_flags(
        {"stt_enabled": True, "srt_enabled": False}) == (False, True)
    assert config.legacy_subtitle_flags(
        {"stt_enabled": False, "txt_enabled": True}) == (False, True)
    assert config.legacy_subtitle_flags(
        {"stt_enabled": True, "srt_enabled": True, "txt_enabled": False}) == (True, False)


def test_module_available():
    assert config.module_available("json") is True
    assert config.module_available("definitely_not_a_module_xyz") is False

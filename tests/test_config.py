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
    assert set(config.option_values(config.SIZE_OPTIONS)) == {"1080p", "720p", "orig"}
    assert config.SIZE_TARGETS["1080p"] == (1920, 1080)
    assert config.SIZE_TARGETS["720p"] == (1280, 720)

    assert config.STT_OFF == "off"
    assert ("off", "关闭（不识别）") in config.STT_MODEL_OPTIONS
    assert config.DEFAULT_STT_MODEL in config.option_values(config.STT_MODEL_OPTIONS)
    assert config.DEFAULT_STT_LANG in config.option_values(config.STT_LANG_OPTIONS)
    assert config.DEFAULT_DENOISE == "arnndn"
    assert ("off", "关闭") in config.DENOISE_OPTIONS
    assert config.DEFAULT_DENOISE in config.option_values(config.DENOISE_OPTIONS)


def test_option_tables_are_value_label_pairs():
    """四组选项均为 (内部值, 显示文案)：内部值唯一、文案唯一、顺序稳定。"""
    for options in (config.SIZE_OPTIONS, config.STT_MODEL_OPTIONS,
                    config.STT_LANG_OPTIONS, config.DENOISE_OPTIONS):
        assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in options)
        values = config.option_values(options)
        labels = config.option_labels(options)
        assert len(values) == len(set(values))
        assert len(labels) == len(set(labels))
        assert all(value and label for value, label in options)

    # 选项集合与拆分前完全一致（不新增、不删除）
    assert config.option_labels(config.SIZE_OPTIONS) == [
        "1080p (1920x1080)", "720p (1280x720)", "原图尺寸（仅偶数修正）"]
    assert config.option_values(config.STT_MODEL_OPTIONS) == [
        "off", "large-v3-turbo", "medium", "small", "base", "tiny"]
    assert config.option_values(config.STT_LANG_OPTIONS) == ["auto", "zh", "en"]
    assert config.option_values(config.DENOISE_OPTIONS) == ["off", "arnndn", "gtcrn"]


def test_option_label_maps_internal_value():
    assert config.option_label(config.SIZE_OPTIONS, "720p") == "720p (1280x720)"
    assert config.option_label(config.STT_MODEL_OPTIONS, "tiny") == "tiny（75 MB · 极速）"
    # 也容忍直接传入旧显示文案（旧配置迁移）
    assert config.option_label(config.DENOISE_OPTIONS, "关闭") == "关闭"
    # 无法识别时用默认值对应的文案
    assert config.option_label(config.STT_MODEL_OPTIONS, "??",
                               config.DEFAULT_STT_MODEL) == "large-v3-turbo（1.55 GB · 精度优先）"


def test_resolve_option_accepts_internal_value_and_legacy_label():
    assert config.resolve_option(config.SIZE_OPTIONS, "720p", "1080p") == ("720p", True)
    assert config.resolve_option(
        config.SIZE_OPTIONS, "720p (1280x720)", "1080p") == ("720p", True)
    assert config.resolve_option(
        config.DENOISE_OPTIONS, "轻度 · RNNoise（推荐）", "arnndn") == ("arnndn", True)
    assert config.resolve_option(
        config.STT_LANG_OPTIONS, "中文", "auto") == ("zh", True)


def test_resolve_option_unknown_falls_back_to_explicit_default():
    value, recognized = config.resolve_option(
        config.STT_MODEL_OPTIONS, "不存在的模型", config.DEFAULT_STT_MODEL)
    assert (value, recognized) == (config.DEFAULT_STT_MODEL, False)
    # 关键：回退目标是默认模型而不是第一项（"off" 会静默关闭识别）
    assert value != config.STT_OFF

    assert config.resolve_option(config.SIZE_OPTIONS, "", "1080p") == ("1080p", True)
    assert config.resolve_option(config.SIZE_OPTIONS, None, "720p") == ("720p", True)
    assert config.resolve_option(config.SIZE_OPTIONS, "??", "720p") == ("720p", False)


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

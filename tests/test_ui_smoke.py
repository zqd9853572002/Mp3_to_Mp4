# -*- coding: utf-8 -*-
"""主窗口冒烟测试：控件存在、三组布局、联动置灰、值/文案分离与主按钮可用性。"""

import time

import pytest

tk = pytest.importorskip("tkinter")

from mp3tom4.config import (  # noqa: E402
    APP_TITLE,
    APP_VERSION,
    DEFAULT_STT_MODEL,
    DENOISE_OPTIONS,
    SIZE_OPTIONS,
    STT_MODEL_OPTIONS,
)
from mp3tom4.ui import main_window as mw  # noqa: E402
from mp3tom4.ui import texts  # noqa: E402

KEY_WIDGETS = [
    "lbl_engine", "btn_engine", "btn_redetect",
    "btn_audio", "lbl_audio",
    "cmb_denoise", "cmb_model", "cmb_lang",
    "chk_srt", "chk_txt",
    "chk_mux_original", "chk_mux_denoised",
    "btn_img", "lbl_img", "cmb_size",
    "btn_dir", "lbl_dir",
    "btn_start", "btn_cancel",
    "progress", "text_area",
    "size_var", "progress_var", "stage_var", "stt_model_var", "stt_lang_var",
    "denoise_var", "srt_var", "txt_var", "mux_original_var", "mux_denoised_var",
    "groups",
]


def _make_app(monkeypatch, cfg=None, discover=None):
    """构建窗口，断开真实配置读写与 ffmpeg 探测，并记录每次落盘内容。"""
    saved = []
    monkeypatch.setattr(mw, "load_config", lambda: dict(cfg or {}))
    monkeypatch.setattr(mw, "save_config", lambda data: saved.append(dict(data)))
    monkeypatch.setattr(mw, "discover_ffmpeg", discover or (lambda saved_path=None: ([], [])))

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无可用显示器")

    root.withdraw()
    return root, mw.AudioToVideoApp(root), saved


@pytest.fixture()
def app(monkeypatch):
    root, application, _saved = _make_app(monkeypatch)
    try:
        yield root, application
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _group_title_labels(frame):
    return {str(w.cget("text")) for w in frame.winfo_children() if isinstance(w, tk.Label)}


def test_window_builds_and_layout(app):
    root, gui = app
    root.update()

    for name in KEY_WIDGETS:
        assert hasattr(gui, name), f"缺少控件/变量: {name}"

    assert gui.btn_start.cget("text") == texts.BTN_START
    assert gui.btn_cancel.cget("text") == texts.BTN_CANCEL
    assert gui.progress.cget("maximum") == 100.0
    assert gui.stage_var.get() == texts.VALIDATE_NO_AUDIO
    assert str(gui.btn_start.cget("state")) == "disabled"
    assert str(gui.btn_cancel.cget("state")) == "disabled"

    assert gui.root.title() == texts.WINDOW_TITLE.format(title=APP_TITLE, version=APP_VERSION)
    welcome = gui.text_area.get("1.0", "end")
    assert "欢迎使用" in welcome
    # 日志区高度必须保持不变（三组布局不得挤压日志）
    assert int(gui.text_area.cget("height")) == 10

    root.after(1500, root.destroy)
    started = time.time()
    root.mainloop()
    assert time.time() - started < 10


def test_option_groups_present(app):
    """A/B/C 三个分组容器与标题都存在，且各控件归属正确。"""
    _, gui = app

    for title in (texts.GROUP_INPUT, texts.GROUP_OPTIONS_A,
                  texts.GROUP_OPTIONS_B, texts.GROUP_OPTIONS_C, texts.GROUP_OUTPUT):
        assert title in gui.groups, f"缺少分组: {title}"
        inner = gui.groups[title]
        assert inner.winfo_exists()
        assert title in _group_title_labels(inner), f"分组标题缺失: {title}"

    assert texts.GROUP_OPTIONS_A == "选项 A · 降噪"
    assert texts.GROUP_OPTIONS_B == "选项 B · 识别与字幕"
    assert texts.GROUP_OPTIONS_C == "选项 C · 视频生成"

    # 降噪只在 A；识别/字幕只在 B；视频相关只在 C
    assert gui.cmb_denoise.master.master is gui.groups[texts.GROUP_OPTIONS_A]
    assert gui.cmb_model.master.master is gui.groups[texts.GROUP_OPTIONS_B]
    assert gui.cmb_lang.master.master is gui.groups[texts.GROUP_OPTIONS_B]
    assert gui.chk_srt.master.master is gui.groups[texts.GROUP_OPTIONS_B]
    assert gui.chk_txt.master.master is gui.groups[texts.GROUP_OPTIONS_B]
    assert gui.chk_mux_original.master.master is gui.groups[texts.GROUP_OPTIONS_C]
    assert gui.chk_mux_denoised.master.master is gui.groups[texts.GROUP_OPTIONS_C]
    assert gui.cmb_size.master.master is gui.groups[texts.GROUP_OPTIONS_C]


def test_default_options_and_start_availability(app):
    _, gui = app

    # 默认：识别模型=large-v3-turbo、降噪=RNNoise，因此「只开降噪」也是可执行任务
    assert gui.stt_model_var.get() == "large-v3-turbo"
    assert gui.denoise_var.get() == "arnndn"

    gui.audio_files = ["C:/fake/a.mp3"]
    gui._sync_options()

    assert gui.stage_var.get() == texts.STAGE_READY_HINT.format(
        count=1, actions=texts.ACT_ONLY_DENOISE)
    assert str(gui.btn_start.cget("state")) == "normal"


def test_linkage_greying_rules(app):
    _, gui = app
    gui.audio_files = ["C:/fake/a.mp3"]

    # 降噪=关闭 → 降噪 MP4 复选框置灰，且「无任何处理方式」时不可开始
    gui.set_option(gui.cmb_denoise, "off")
    assert str(gui.chk_mux_denoised.cget("state")) == "disabled"
    assert gui.stage_var.get() == texts.VALIDATE_NO_ACTION
    assert str(gui.btn_start.cget("state")) == "disabled"

    # 识别模型=关闭 → 语种与字幕格式一并置灰
    gui.set_option(gui.cmb_model, "off")
    assert str(gui.cmb_lang.cget("state")) == "disabled"
    assert str(gui.chk_srt.cget("state")) == "disabled"
    assert str(gui.chk_txt.cget("state")) == "disabled"

    # 勾原声 MP4 但没有封面 → 提示缺封面且不可开始
    gui.mux_original_var.set(True)
    gui._sync_options()
    assert gui.stage_var.get() == texts.VALIDATE_NEED_COVER
    assert str(gui.btn_start.cget("state")) == "disabled"
    assert gui.btn_img.cget("bg") == "#D97706"

    # 补上封面 → 可开始
    gui.image_path = "C:/fake/cover.png"
    gui._sync_options()
    assert gui.stage_var.get() == texts.STAGE_READY_HINT.format(
        count=1, actions=texts.ACT_MUX_ORIGINAL)
    assert str(gui.btn_start.cget("state")) == "normal"

    # 识别模型打开后语种恢复可编辑、字幕复选框解禁
    gui.set_option(gui.cmb_model, "tiny")
    assert str(gui.cmb_lang.cget("state")) == "readonly"
    assert str(gui.chk_srt.cget("state")) == "normal"
    assert str(gui.chk_txt.cget("state")) == "normal"


def test_config_persists_internal_values(monkeypatch):
    """配置文件里写入的必须是内部值，而不是下拉框显示文案。"""
    root, gui, saved = _make_app(monkeypatch)
    try:
        gui.set_option(gui.cmb_size, "720p")
        gui.set_option(gui.cmb_model, "large-v3-turbo")
        gui.set_option(gui.cmb_lang, "zh")
        gui.set_option(gui.cmb_denoise, "gtcrn")

        last = saved[-1]
        assert last["size_mode"] == "720p"
        assert last["stt_model"] == "large-v3-turbo"
        assert last["stt_language"] == "zh"
        assert last["denoise_mode"] == "gtcrn"

        # 中文/带单位文案不得写入配置
        assert last["size_mode"] != "720p (1280x720)"
        assert last["denoise_mode"] != "强力 · GTCRN（神经网络）"
        # 下拉框仍然显示文案
        assert gui.cmb_size.get() == "720p (1280x720)"
        assert gui.cmb_denoise.get() == "强力 · GTCRN（神经网络）"
    finally:
        root.destroy()


def test_legacy_chinese_config_maps_to_internal(monkeypatch):
    """旧配置里存的是中文显示文案 → 加载后 Tk 变量应对应内部值。"""
    legacy = {
        "size_mode": "720p (1280x720)",
        "stt_model": "关闭（不识别）",
        "stt_language": "中文",
        "denoise_mode": "轻度 · RNNoise（推荐）",
    }
    root, gui, _saved = _make_app(monkeypatch, cfg=legacy)
    try:
        assert gui.size_var.get() == "720p"
        assert gui.stt_model_var.get() == "off"
        assert gui.stt_lang_var.get() == "zh"
        assert gui.denoise_var.get() == "arnndn"
    finally:
        root.destroy()


def test_display_labels_come_from_options():
    """下拉框显示项就是选项表文案，且与内部值一一对应。"""
    from mp3tom4.config import option_labels

    assert option_labels(SIZE_OPTIONS) == [
        "1080p (1920x1080)", "720p (1280x720)", "原图尺寸（仅偶数修正）"]
    assert option_labels(DENOISE_OPTIONS) == [
        "关闭", "轻度 · RNNoise（推荐）", "强力 · GTCRN（神经网络）"]
    assert "large-v3-turbo（1.55 GB · 精度优先）" in option_labels(STT_MODEL_OPTIONS)


def test_refresh_ffmpeg_replaces_stale_path(monkeypatch):
    """原路径已失效时才采用新的探测结果。"""
    def fake_discover(saved_path=None):
        return ([{"path": "C:/auto/ffmpeg.exe", "version": "ffmpeg version 7.0",
                  "libx264": True, "aac": True}], [])

    root, gui, _saved = _make_app(
        monkeypatch, cfg={"ffmpeg_path": "C:/gone/ffmpeg.exe"}, discover=fake_discover)
    try:
        gui.refresh_ffmpeg()
        assert gui.ffmpeg_path == "C:/auto/ffmpeg.exe"
        assert gui.cfg["ffmpeg_path"] == "C:/auto/ffmpeg.exe"
    finally:
        root.destroy()


def test_lock_ui_toggles_buttons(app):
    _, gui = app
    gui.audio_files = ["C:/fake/a.mp3"]
    gui._sync_options()

    gui.lock_ui(True)
    assert gui.btn_start.cget("text") == texts.BTN_START_BUSY
    assert str(gui.btn_start.cget("state")) == "disabled"
    assert str(gui.btn_cancel.cget("state")) == "normal"
    assert str(gui.btn_audio.cget("state")) == "disabled"
    assert str(gui.cmb_size.cget("state")) == "disabled"

    gui.lock_ui(False)
    assert gui.btn_start.cget("text") == texts.BTN_START
    assert str(gui.btn_cancel.cget("state")) == "disabled"
    assert str(gui.btn_audio.cget("state")) == "normal"
    assert str(gui.cmb_size.cget("state")) == "readonly"


def test_build_plan_from_widgets(app):
    _, gui = app
    gui.audio_files = ["C:/fake/a.mp3"]
    gui.output_dir = "C:/out"
    gui.image_path = "C:/fake/cover.png"
    gui.ffmpeg_path = "C:/ffmpeg.exe"
    gui.set_option(gui.cmb_size, "720p")
    gui.set_option(gui.cmb_model, "off")
    gui.set_option(gui.cmb_denoise, "off")
    gui.srt_var.set(True)
    gui.mux_original_var.set(True)

    plan = gui._build_plan()

    assert plan.audio_files == ["C:/fake/a.mp3"]
    assert plan.output_dir == "C:/out"
    assert plan.ffmpeg_path == "C:/ffmpeg.exe"
    assert plan.size_mode == "720p"
    assert plan.model_name is None
    assert plan.denoise_mode is None
    assert plan.mux_original is True
    assert plan.mux_denoised is False
    assert plan.need_stt is False

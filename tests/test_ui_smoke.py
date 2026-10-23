# -*- coding: utf-8 -*-
"""主窗口冒烟测试：控件存在、属性名正确、联动置灰与主按钮可用性。"""

import time

import pytest

tk = pytest.importorskip("tkinter")

from mp3tom4.config import APP_TITLE, APP_VERSION, DENOISE_MODES, STT_MODELS  # noqa: E402
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
]


@pytest.fixture()
def app(monkeypatch):
    """构建窗口，并断开真实配置读写与 ffmpeg 探测，保证测试离线可重复。"""
    monkeypatch.setattr(mw, "load_config", lambda: {})
    monkeypatch.setattr(mw, "save_config", lambda cfg: None)
    monkeypatch.setattr(mw, "discover_ffmpeg", lambda saved=None: ([], []))

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无可用显示器")

    root.withdraw()
    application = mw.AudioToVideoApp(root)
    try:
        yield root, application
    finally:
        try:
            root.destroy()
        except Exception:
            pass


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

    root.after(1500, root.destroy)
    started = time.time()
    root.mainloop()
    assert time.time() - started < 10


def test_default_options_and_start_availability(app):
    _, gui = app

    # 默认：识别模型=large-v3-turbo、降噪=RNNoise，因此「只开降噪」也是可执行任务
    assert gui.stt_model_var.get() == gui._label_from_value(STT_MODELS, "large-v3-turbo")
    assert gui.denoise_var.get() == gui._label_from_value(DENOISE_MODES, "arnndn")

    gui.audio_files = ["C:/fake/a.mp3"]
    gui._sync_options()

    assert gui.stage_var.get() == texts.STAGE_READY_HINT.format(
        count=1, actions=texts.ACT_ONLY_DENOISE)
    assert str(gui.btn_start.cget("state")) == "normal"


def test_linkage_greying_rules(app):
    _, gui = app
    gui.audio_files = ["C:/fake/a.mp3"]

    # 降噪=关闭 → 降噪 MP4 复选框置灰，且「无任何处理方式」时不可开始
    gui.cmb_denoise.set(gui._label_from_value(DENOISE_MODES, "off"))
    gui._on_option_change()
    assert str(gui.chk_mux_denoised.cget("state")) == "disabled"
    assert gui.stage_var.get() == texts.VALIDATE_NO_ACTION
    assert str(gui.btn_start.cget("state")) == "disabled"

    # 识别模型=关闭 → 语种与字幕格式一并置灰
    gui.cmb_model.set(gui._label_from_value(STT_MODELS, "off"))
    gui._on_option_change()
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
    gui.cmb_model.set(gui._label_from_value(STT_MODELS, "tiny"))
    gui._on_option_change()
    assert str(gui.cmb_lang.cget("state")) == "readonly"
    assert str(gui.chk_srt.cget("state")) == "normal"
    assert str(gui.chk_txt.cget("state")) == "normal"


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
    from mp3tom4.config import SIZE_MODES

    _, gui = app
    gui.audio_files = ["C:/fake/a.mp3"]
    gui.output_dir = "C:/out"
    gui.image_path = "C:/fake/cover.png"
    gui.ffmpeg_path = "C:/ffmpeg.exe"
    gui.cmb_size.set("720p (1280x720)")
    gui.cmb_model.set(gui._label_from_value(STT_MODELS, "off"))
    gui.cmb_denoise.set(gui._label_from_value(DENOISE_MODES, "off"))
    gui.srt_var.set(True)
    gui.mux_original_var.set(True)

    plan = gui._build_plan()

    assert plan.audio_files == ["C:/fake/a.mp3"]
    assert plan.output_dir == "C:/out"
    assert plan.ffmpeg_path == "C:/ffmpeg.exe"
    assert plan.size_mode == SIZE_MODES["720p (1280x720)"]
    assert plan.model_name is None
    assert plan.denoise_mode is None
    assert plan.mux_original is True
    assert plan.mux_denoised is False
    assert plan.need_stt is False

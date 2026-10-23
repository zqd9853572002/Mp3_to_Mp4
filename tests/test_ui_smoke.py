# -*- coding: utf-8 -*-
"""主窗口冒烟测试：控件存在、三组布局、联动置灰、值/文案分离、主按钮可用性
以及三语即时切换（控件文案 / 下拉框 / 阶段文本 / 日志语言）。
"""

import time

import pytest

tk = pytest.importorskip("tkinter")

from mp3tom4 import i18n  # noqa: E402
from mp3tom4.config import (  # noqa: E402
    APP_VERSION,
    DEFAULT_STT_MODEL,
    DENOISE_OPTIONS,
    SIZE_OPTIONS,
    STT_MODEL_OPTIONS,
)
from mp3tom4.i18n import get_language, set_language, t  # noqa: E402
from mp3tom4.ui import main_window as mw  # noqa: E402

KEY_WIDGETS = [
    "lbl_engine", "btn_engine", "btn_redetect",
    "btn_audio", "lbl_audio",
    "cmb_denoise", "cmb_model", "cmb_lang",
    "chk_srt", "chk_txt",
    "chk_mux_original", "chk_mux_denoised",
    "btn_img", "lbl_img", "cmb_size",
    "btn_dir", "lbl_dir",
    "btn_start", "btn_cancel", "cmb_language",
    "progress", "text_area",
    "size_var", "progress_var", "stage_var", "stt_model_var", "stt_lang_var",
    "denoise_var", "srt_var", "txt_var", "mux_original_var", "mux_denoised_var",
    "lang_display_var", "groups",
]

GROUP_KEYS = [
    "group.input", "group.options_a", "group.options_b",
    "group.options_c", "group.output",
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


def _group_title_texts(frame):
    """分组框标题实际显示的文本（兼容 textvariable 绑定）。"""
    found = set()
    for widget in frame.winfo_children():
        if not isinstance(widget, tk.Label):
            continue
        text = str(widget.cget("text"))
        if text:
            found.add(text)
        var_name = str(widget.cget("textvariable"))
        if var_name:
            found.add(str(widget.tk.globalgetvar(var_name)))
    return found


def test_window_builds_and_layout(app):
    root, gui = app
    root.update()

    for name in KEY_WIDGETS:
        assert hasattr(gui, name), f"缺少控件/变量: {name}"

    assert gui.btn_start.cget("text") == t("btn.start")
    assert gui.btn_cancel.cget("text") == t("btn.cancel")
    assert gui.progress.cget("maximum") == 100.0
    assert gui.stage_var.get() == t("stage.need_audio")
    assert str(gui.btn_start.cget("state")) == "disabled"
    assert str(gui.btn_cancel.cget("state")) == "disabled"

    assert root.title() == t("app.window_title", title=t("app.title"), version=APP_VERSION)
    welcome = gui.text_area.get("1.0", "end")
    assert t("app.title") in welcome
    # 日志区高度必须保持不变（三组布局不得挤压日志）
    assert int(gui.text_area.cget("height")) == 10

    root.after(1500, root.destroy)
    started = time.time()
    root.mainloop()
    assert time.time() - started < 10


def test_option_groups_present(app):
    """A/B/C 三个分组容器与标题都存在，且各控件归属正确。"""
    _, gui = app

    for key in GROUP_KEYS:
        assert key in gui.groups, f"缺少分组: {key}"
        inner = gui.groups[key]
        assert inner.winfo_exists()
        assert t(key) in _group_title_texts(inner), f"分组标题缺失: {key}"

    # 降噪只在 A；识别/字幕只在 B；视频相关只在 C
    assert gui.cmb_denoise.master.master is gui.groups["group.options_a"]
    assert gui.cmb_model.master.master is gui.groups["group.options_b"]
    assert gui.cmb_lang.master.master is gui.groups["group.options_b"]
    assert gui.chk_srt.master.master is gui.groups["group.options_b"]
    assert gui.chk_txt.master.master is gui.groups["group.options_b"]
    assert gui.chk_mux_original.master.master is gui.groups["group.options_c"]
    assert gui.chk_mux_denoised.master.master is gui.groups["group.options_c"]
    assert gui.cmb_size.master.master is gui.groups["group.options_c"]


def test_default_options_and_start_availability(app):
    _, gui = app

    # 默认：识别模型=large-v3-turbo、降噪=RNNoise，因此「只开降噪」也是可执行任务
    assert gui.stt_model_var.get() == "large-v3-turbo"
    assert gui.denoise_var.get() == "arnndn"

    gui.audio_files = ["C:/fake/a.mp3"]
    gui._sync_options()

    assert gui.stage_var.get() == t(
        "stage.ready_hint", count=1, actions=t("act.only_denoise"))
    assert str(gui.btn_start.cget("state")) == "normal"


def test_linkage_greying_rules(app):
    _, gui = app
    gui.audio_files = ["C:/fake/a.mp3"]

    # 降噪=关闭 → 降噪 MP4 复选框置灰，且「无任何处理方式」时不可开始
    gui.set_option(gui.cmb_denoise, "off")
    assert str(gui.chk_mux_denoised.cget("state")) == "disabled"
    assert gui.stage_var.get() == t("stage.need_action")
    assert str(gui.btn_start.cget("state")) == "disabled"

    # 识别模型=关闭 → 语种与字幕格式一并置灰
    gui.set_option(gui.cmb_model, "off")
    assert str(gui.cmb_lang.cget("state")) == "disabled"
    assert str(gui.chk_srt.cget("state")) == "disabled"
    assert str(gui.chk_txt.cget("state")) == "disabled"

    # 勾原声 MP4 但没有封面 → 提示缺封面且不可开始
    gui.mux_original_var.set(True)
    gui._sync_options()
    assert gui.stage_var.get() == t("stage.need_cover")
    assert str(gui.btn_start.cget("state")) == "disabled"
    assert gui.btn_img.cget("bg") == "#D97706"

    # 补上封面 → 可开始
    gui.image_path = "C:/fake/cover.png"
    gui._sync_options()
    assert gui.stage_var.get() == t(
        "stage.ready_hint", count=1, actions=t("act.mux_original"))
    assert str(gui.btn_start.cget("state")) == "normal"

    # 识别模型打开后语种恢复可编辑、字幕复选框解禁
    gui.set_option(gui.cmb_model, "tiny")
    assert str(gui.cmb_lang.cget("state")) == "readonly"
    assert str(gui.chk_srt.cget("state")) == "normal"
    assert str(gui.chk_txt.cget("state")) == "normal"


def test_denoise_off_auto_unchecks_denoised_mp4(app):
    """降噪切到关闭 → 已勾选的「降噪音频配图 MP4」自动取消并给出说明。"""
    _, gui = app
    gui.audio_files = ["C:/fake/a.mp3"]
    gui.image_path = "C:/fake/cover.png"

    gui.set_option(gui.cmb_denoise, "arnndn")
    gui.mux_denoised_var.set(True)
    gui._sync_options()
    assert gui.mux_denoised_var.get() is True
    assert str(gui.chk_mux_denoised.cget("state")) == "normal"

    gui.set_option(gui.cmb_denoise, "off")

    assert gui.mux_denoised_var.get() is False
    assert str(gui.chk_mux_denoised.cget("state")) == "disabled"
    assert t("stage.denoise_off_unchecked") in gui.stage_var.get()
    # 自动取消必须落盘，避免下次启动又从配置里「复活」
    assert gui.cfg["mux_denoised"] is False


def test_denoise_reenable_does_not_recheck(app):
    """反向：重新开启降噪不会自动恢复勾选，由用户重新决定。"""
    _, gui = app
    gui.audio_files = ["C:/fake/a.mp3"]

    gui.mux_denoised_var.set(True)
    gui._sync_options()
    gui.set_option(gui.cmb_denoise, "off")
    assert gui.mux_denoised_var.get() is False

    gui.set_option(gui.cmb_denoise, "arnndn")
    assert gui.mux_denoised_var.get() is False
    assert str(gui.chk_mux_denoised.cget("state")) == "normal"


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
        assert last["ui_language"] == get_language()

        # 下拉框仍然显示文案（而不是内部值）
        assert gui.cmb_size.get() == t("opt.size.720p")
        assert gui.cmb_denoise.get() == t("opt.denoise.gtcrn")
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


def test_unknown_model_falls_back_to_default(monkeypatch):
    """未知模型名 → 回退默认模型（不能回退到 "off" 静默关闭识别），并打日志。"""
    root, gui, _saved = _make_app(monkeypatch, cfg={"stt_model": "不存在的模型"})
    try:
        assert gui.stt_model_var.get() == DEFAULT_STT_MODEL
        assert gui.stt_model_var.get() != "off"

        root.update()
        root.update()
        log_text = gui.text_area.get("1.0", "end")
        assert "无法识别" in log_text
        assert DEFAULT_STT_MODEL in log_text
    finally:
        root.destroy()


def test_display_labels_come_from_options():
    """下拉框显示项就是选项表词条的翻译，且与内部值一一对应。"""
    from mp3tom4.config import option_labels

    assert option_labels(SIZE_OPTIONS) == [
        t("opt.size.1080p"), t("opt.size.720p"), t("opt.size.orig")]
    assert option_labels(DENOISE_OPTIONS) == [
        t("opt.denoise.off"), t("opt.denoise.arnndn"), t("opt.denoise.gtcrn")]
    assert t("opt.model.large-v3-turbo") in option_labels(STT_MODEL_OPTIONS)


def test_filetypes_follow_language():
    """文件对话框过滤器文案已从 config 移到 UI 层，并随语言变化。"""
    assert mw.audio_filetypes()[0][0] == t("filetype.audio")
    assert mw.image_filetypes()[0][0] == t("filetype.image")
    assert mw.audio_filetypes()[-1] == (t("filetype.all_files"), "*.*")

    set_language("en", persist=False)
    try:
        assert mw.audio_filetypes()[0][0] == "All supported audio"
        assert mw.image_filetypes()[0][0] == "Image files"
    finally:
        set_language("zh_CN", persist=False)


def test_refresh_ffmpeg_keeps_saved_usable_path(monkeypatch):
    """重新检测不得覆盖仍然可用的手动指定路径。"""
    manual = "C:/MyFFmpeg/bin/ffmpeg.exe"
    auto = "C:/auto/ffmpeg.exe"

    def fake_discover(saved_path=None):
        return ([
            {"path": auto, "version": "ffmpeg version 7.0", "libx264": True, "aac": True},
            {"path": manual, "version": "ffmpeg version 6.1", "libx264": True, "aac": True},
        ], [])

    root, gui, _saved = _make_app(
        monkeypatch, cfg={"ffmpeg_path": manual}, discover=fake_discover)
    try:
        gui.refresh_ffmpeg()
        assert gui.ffmpeg_path == manual
        assert gui.cfg["ffmpeg_path"] == manual

        root.update()
        root.update()
        assert t("log.ffmpeg_kept", path=manual) in gui.text_area.get("1.0", "end")
    finally:
        root.destroy()


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
    assert gui.btn_start.cget("text") == t("btn.start_busy")
    assert str(gui.btn_start.cget("state")) == "disabled"
    assert str(gui.btn_cancel.cget("state")) == "normal"
    assert str(gui.btn_audio.cget("state")) == "disabled"
    assert str(gui.cmb_size.cget("state")) == "disabled"

    gui.lock_ui(False)
    assert gui.btn_start.cget("text") == t("btn.start")
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


# ==================== 三语即时切换 ====================
def test_language_switch_updates_key_widgets(app):
    """切到 en 后关键控件变英文，切回中文恢复；窗口不重建、状态不丢。"""
    root, gui = app
    gui.audio_files = ["C:/fake/a.mp3"]
    gui._sync_options()

    gui.apply_language("en")
    root.update()

    assert get_language() == "en"
    assert gui.btn_start.cget("text") == "▶ Start"
    assert gui.btn_audio.cget("text") == "Choose Audio"
    assert gui.btn_dir.cget("text") == "Choose Folder"
    assert gui.btn_cancel.cget("text") == "Cancel"
    assert t("group.options_a") in _group_title_texts(gui.groups["group.options_a"])
    assert "Options A · Noise Reduction" in _group_title_texts(
        gui.groups["group.options_a"])
    assert root.title().startswith("Fast Audio to MP4 Batch Engine")

    # 状态保留：窗口对象、音频选择、阶段文本都还在
    assert gui.audio_files == ["C:/fake/a.mp3"]
    assert gui.stage_var.get().startswith("Ready")

    gui.apply_language("zh_CN")
    root.update()
    assert gui.btn_start.cget("text") == "▶ 开始执行"
    assert gui.btn_audio.cget("text") == "选择音频"
    assert gui.stage_var.get() == t(
        "stage.ready_hint", count=1, actions=t("act.only_denoise"))


def test_language_switch_rerenders_combos(app):
    """下拉框显示文案重渲染，但内部值变量保持不变。"""
    _, gui = app
    gui.set_option(gui.cmb_model, "large-v3-turbo")

    gui.apply_language("en")
    assert gui.cmb_model.get() == "large-v3-turbo (1.55 GB · best accuracy)"
    assert gui.stt_model_var.get() == "large-v3-turbo"

    gui.apply_language("zh_TW")
    assert gui.cmb_model.get() == "large-v3-turbo（1.55 GB · 精度優先）"
    assert gui.stt_model_var.get() == "large-v3-turbo"
    assert gui.cmb_denoise.get() == "輕度 · RNNoise（推薦）"
    assert gui.denoise_var.get() == "arnndn"


def test_language_switch_refreshes_stage(app):
    """停留在「就绪」时切换语言，阶段文本按新语言重建（含动作名）。"""
    _, gui = app
    gui.audio_files = ["C:/fake/a.mp3"]
    gui._sync_options()

    gui.apply_language("en")
    assert gui.stage_var.get() == "Ready · 1 file(s) · Denoise only"

    gui.apply_language("zh_TW")
    assert gui.stage_var.get() == "就緒 · 1 個音訊 · 僅降噪音訊"

    gui.apply_language("zh_CN")
    assert gui.stage_var.get() == "就绪 · 1 个音频 · 仅降噪音频"


def test_log_uses_new_language_after_switch(app):
    """切换语言后新写入的日志使用新语言，历史日志保持原样。"""
    root, gui = app
    root.update()
    history = gui.text_area.get("1.0", "end").rstrip("\n")

    gui.apply_language("en")
    gui.cancel_processing()
    root.update()
    log_text = gui.text_area.get("1.0", "end")

    assert log_text.startswith(history), "历史日志内容不得被翻译或清空"
    appended = log_text[len(history):]
    assert "Cancel requested" in appended
    assert "已请求取消" not in appended
    assert gui.stage_var.get() == "Cancelling..."
    gui._stop = False
    gui.lock_ui(False)


def test_language_switch_persists_choice(monkeypatch):
    """选择语言写入配置 ui_language（内部 code）。"""
    root, gui, saved = _make_app(monkeypatch)
    try:
        gui.apply_language("zh_TW")
        assert gui.cfg["ui_language"] == "zh_TW"
        assert saved[-1]["ui_language"] == "zh_TW"
    finally:
        root.destroy()
        set_language("zh_CN", persist=False)


def test_language_dropdown_lists_self_names(app):
    """语言下拉展示各语言自称，且选中项与当前语言一致。"""
    _, gui = app
    assert list(gui.cmb_language.cget("values")) == ["简体中文", "繁體中文", "English"]
    assert gui.lang_display_var.get() == "简体中文"

    gui.apply_language("en")
    assert gui.lang_display_var.get() == "English"
    assert gui.lang_label_var.get() == "Language"
    assert i18n.language_label("zh_TW") == "繁體中文"

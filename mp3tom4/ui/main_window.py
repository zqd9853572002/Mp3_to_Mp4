# -*- coding: utf-8 -*-
"""主窗口：布局、联动置灰、文件选择、配置持久化、日志/进度与线程启动。

业务执行全部交给 `pipeline.Pipeline`，本模块不直接调用 ffmpeg/asr 函数。
所有用户可见文案均通过 `mp3tom4.i18n.t()` 取得，并绑定到 `tk.StringVar`，
因此切换语言时只需重设变量，无需销毁重建窗口（输入状态与历史日志都保留）。
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from ..asr import whisper_model_ready
from ..config import (
    APP_VERSION,
    AUDIO_EXTS,
    DEFAULT_DENOISE,
    DEFAULT_MODE,
    DEFAULT_STT_LANG,
    DEFAULT_STT_MODEL,
    DENOISE_OPTIONS,
    IMAGE_EXTS,
    SIZE_OPTIONS,
    STT_LANG_OPTIONS,
    STT_MODEL_OPTIONS,
    legacy_subtitle_flags,
    load_config,
    module_available,
    option_label,
    option_labels,
    resolve_option,
    save_config,
)
from ..ffmpeg import discover_ffmpeg, ffmpeg_info
from ..i18n import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    get_language,
    language_label,
    set_language,
    t,
)
from ..pipeline import Pipeline, build_plan, denoise_desc, option_flags
from . import widgets

# 纯 ASCII 分隔线，无需翻译
LOG_TASK_HEADER = "=" * 64 + "\n"


def audio_filetypes():
    """音频对话框过滤器（文案随当前语言生成，故从 config 移到 UI 层）。"""
    return [
        (t("filetype.audio"), " ".join("*" + ext for ext in AUDIO_EXTS)),
        (t("filetype.all_files"), "*.*"),
    ]


def image_filetypes():
    """图片对话框过滤器（文案随当前语言生成）。"""
    return [
        (t("filetype.image"), " ".join("*" + ext for ext in IMAGE_EXTS)),
        (t("filetype.all_files"), "*.*"),
    ]


class AudioToVideoApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        # 三组选项比原两组多占一行分组框，高度相应上调；日志区仍保持 height=10
        self.root.geometry("980x1000")
        self.root.minsize(960, 950)
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
        # 初始化期间产生的配置告警，等日志控件创建后再统一输出
        self._startup_warnings = []
        # 下拉框注册表：combo -> (options, 显示文案变量, 内部值变量)
        self._combos = {}
        # 分组容器：词条 key -> 内层 Frame（供联动与测试定位）
        self.groups = {}
        # 文案登记表：[(StringVar, 词条 key, 格式化参数)]，retranslate 据此重设
        self._text_bindings = []
        # 当前阶段以「词条 key + 参数」保存，切换语言时可重新生成
        self._stage_key = None
        self._stage_kwargs = {}
        self._stage_note_key = None
        # FFmpeg 状态条状态：detecting / ok / missing
        self._engine_state = "detecting"

        # 旧配置（v4.0）只有一个 stt_enabled：等于「同时生成两种格式」
        srt_default, txt_default = legacy_subtitle_flags(self.cfg)

        # 所有会随语言变化的文本都走 StringVar
        self.stage_var = tk.StringVar()
        self.engine_var = tk.StringVar()
        self.audio_var = tk.StringVar()
        self.img_var = tk.StringVar()
        self.dir_var = tk.StringVar()
        self.start_var = tk.StringVar()
        self.engine_prefix_var = tk.StringVar()
        self.lang_label_var = tk.StringVar()
        self.lang_display_var = tk.StringVar(value=language_label(get_language()))

        self.set_text(self.engine_prefix_var, "engine.prefix")
        self.set_text(self.engine_var, "engine.detecting")
        self.set_text(self.audio_var, "label.unselected")
        self.set_text(self.img_var, "label.unselected")
        self.set_text(self.dir_var, "label.unselected")
        self.set_text(self.start_var, "btn.start")
        self.set_text(self.lang_label_var, "app.lang_label")

        # Tk 变量一律只存内部值；显示文案由下拉框自己的变量负责
        self.size_var = tk.StringVar(value=self._init_option(
            SIZE_OPTIONS, self.cfg.get("size_mode"), DEFAULT_MODE, "label.size"))
        self.progress_var = tk.DoubleVar(value=0.0)

        self.stt_model_var = tk.StringVar(value=self._init_option(
            STT_MODEL_OPTIONS, self.cfg.get("stt_model"), DEFAULT_STT_MODEL,
            "label.model"))
        self.stt_lang_var = tk.StringVar(value=self._init_option(
            STT_LANG_OPTIONS, self.cfg.get("stt_language"), DEFAULT_STT_LANG,
            "label.language"))
        self.denoise_var = tk.StringVar(value=self._init_option(
            DENOISE_OPTIONS, self.cfg.get("denoise_mode"), DEFAULT_DENOISE,
            "label.denoise"))
        self.srt_var = tk.BooleanVar(value=srt_default)
        self.txt_var = tk.BooleanVar(value=txt_default)
        self.mux_original_var = tk.BooleanVar(value=bool(self.cfg.get("mux_original", False)))
        self.mux_denoised_var = tk.BooleanVar(value=bool(self.cfg.get("mux_denoised", False)))

        self.setup_ui()
        self._restore_saved_selection()
        self.root.title(self._window_title())
        self.root.after(100, self.refresh_ffmpeg)

    # ---------- 文案登记 / 重译 ----------
    def set_text(self, var, key, **kwargs):
        """登记（或更新）一个 StringVar 的词条来源，并立即赋值。"""
        for index, (registered, _key, _kwargs) in enumerate(self._text_bindings):
            if registered is var:
                self._text_bindings[index] = (var, key, dict(kwargs))
                break
        else:
            self._text_bindings.append((var, key, dict(kwargs)))
        var.set(t(key, **kwargs))
        return var

    def _window_title(self):
        return t("app.window_title", title=t("app.title"), version=APP_VERSION)

    def retranslate(self):
        """按当前语言刷新全部静态文案、下拉框与阶段文本（不重建窗口）。"""
        self.root.title(self._window_title())
        for var, key, kwargs in list(self._text_bindings):
            var.set(t(key, **kwargs))

        self.lang_display_var.set(language_label(get_language()))
        for combo, (options, display_var, value_var) in self._combos.items():
            combo.configure(values=option_labels(options))
            display_var.set(option_label(options, value_var.get()))

        self._refresh_engine_label()
        if self._stage_key:
            kwargs = dict(self._stage_kwargs)
            if self._stage_key == "stage.ready_hint":
                kwargs["actions"] = self._actions_text()
            self._set_stage(self._stage_key, note_key=self._stage_note_key, **kwargs)

    def apply_language(self, code):
        """切换语言 → 落盘 → 立即重译（供下拉框与测试共用）。"""
        set_language(code)
        self.cfg["ui_language"] = get_language()
        self._persist()
        self.retranslate()

    def _on_language_pick(self, _event=None):
        label = self.lang_display_var.get()
        code = next(
            (code for code, name in SUPPORTED_LANGUAGES if name == label),
            DEFAULT_LANGUAGE,
        )
        self.apply_language(code)

    # ---------- 配置辅助 ----------
    def _init_option(self, options, raw, default, name_key) -> str:
        """读取配置里的选项值：兼容旧中文文案，无法识别时回退默认值并记账。"""
        value, recognized = resolve_option(options, raw, default)
        if not recognized:
            self._startup_warnings.append(t(
                "log.config_fallback", name=t(name_key), raw=raw, value=value))
        return value

    def _make_combo(self, parent, options, value_var, width):
        """创建「内部值 ↔ 显示文案」分离的下拉框。

        `value_var` 始终保存内部值，下拉框自身绑定另一套显示文案变量。
        """
        display_var = tk.StringVar(value=option_label(options, value_var.get()))
        combo = ttk.Combobox(parent, textvariable=display_var, state="readonly",
                             values=option_labels(options), width=width,
                             font=("Microsoft YaHei", 9))
        combo.bind("<<ComboboxSelected>>", lambda _event: self._on_option_pick(combo))
        self._combos[combo] = (options, display_var, value_var)
        return combo

    def _on_option_pick(self, combo):
        """用户在下拉框里选了新文案 → 换算成内部值后再触发联动。"""
        options, display_var, value_var = self._combos[combo]
        value, _recognized = resolve_option(options, display_var.get(), value_var.get())
        value_var.set(value)
        self._on_option_change()

    def set_option(self, combo, value):
        """以**内部值**程序化设置下拉框（界面与测试共用同一入口）。"""
        options, display_var, value_var = self._combos[combo]
        value, _recognized = resolve_option(options, value, value_var.get())
        display_var.set(option_label(options, value))
        value_var.set(value)
        self._on_option_change()

    def _persist(self):
        self.cfg.update({
            "ffmpeg_path": self.ffmpeg_path,
            "image_path": self.image_path,
            "output_dir": self.output_dir,
            "ui_language": get_language(),
            # 一律写内部值，避免界面文案变化导致旧配置失效
            "size_mode": resolve_option(SIZE_OPTIONS, self.size_var.get(), DEFAULT_MODE)[0],
            "stt_model": resolve_option(
                STT_MODEL_OPTIONS, self.stt_model_var.get(), DEFAULT_STT_MODEL)[0],
            "stt_language": resolve_option(
                STT_LANG_OPTIONS, self.stt_lang_var.get(), DEFAULT_STT_LANG)[0],
            "denoise_mode": resolve_option(
                DENOISE_OPTIONS, self.denoise_var.get(), DEFAULT_DENOISE)[0],
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
        return option_flags(
            resolve_option(STT_MODEL_OPTIONS, self.stt_model_var.get(),
                           DEFAULT_STT_MODEL)[0],
            resolve_option(DENOISE_OPTIONS, self.denoise_var.get(),
                           DEFAULT_DENOISE)[0],
            self.srt_var.get(),
            self.txt_var.get(),
            self.mux_original_var.get(),
            self.mux_denoised_var.get(),
        )

    def _validate_plan(self):
        """返回 (是否可执行, 不可执行时的阶段词条 key)。"""
        flags = self._option_flags()
        if not self.audio_files:
            return False, "stage.need_audio"
        if not (flags["need_stt"] or flags["mux_original"]
                or flags["mux_denoised"] or flags["only_denoise"]):
            return False, "stage.need_action"
        if (flags["mux_original"] or flags["mux_denoised"]) and not self.image_path:
            return False, "stage.need_cover"
        return True, None

    def _actions_text(self):
        """当前计划的动作名（按当前语言拼接）。"""
        flags = self._option_flags()
        keys = []
        if flags["only_denoise"]:
            keys.append("act.only_denoise")
        if flags["need_stt"]:
            keys.append("act.subtitle")
        if flags["mux_original"]:
            keys.append("act.mux_original")
        if flags["mux_denoised"]:
            keys.append("act.mux_denoised")
        return " + ".join(t(key) for key in keys)

    def _set_stage(self, key, note_key=None, **kwargs):
        """记录阶段 key + 参数并渲染；语言切换时可原样重建。"""
        self._stage_key = key
        self._stage_kwargs = dict(kwargs)
        self._stage_note_key = note_key
        text = t(key, **kwargs)
        if note_key:
            text = t("stage.with_note", hint=text, note=t(note_key))
        self.stage_var.set(text)

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

        # 降噪 = 关闭 → 降噪 MP4 置灰，并**自动取消勾选**（否则会被静默跳过）。
        # 反向不自动恢复勾选：重新开启降噪后由用户重新决定。
        auto_unchecked = False
        if flags["denoise_on"]:
            self.chk_mux_denoised.config(state=tk.NORMAL)
        else:
            self.chk_mux_denoised.config(state=tk.DISABLED)
            if self.mux_denoised_var.get():
                self.mux_denoised_var.set(False)
                auto_unchecked = True
                self.cfg["mux_denoised"] = False
                save_config(self.cfg)

        # 封面按钮：没有视频输出时灰色但仍可点击，方便提前准备素材
        if flags["mux_original"] or flags["mux_denoised"]:
            self.btn_img.config(bg="#D97706", fg="white", activebackground="#B45309",
                                activeforeground="white", cursor="hand2")
        else:
            self.btn_img.config(bg="#4A4A4A", fg="#9A9A9A", activebackground="#4A4A4A",
                                activeforeground="#9A9A9A", cursor="hand2")

        # 自动取消的说明要附在提示后面（即使当前计划因「无任何处理方式」不可执行），
        # 与拆分前行为保持一致。
        note_key = "stage.denoise_off_unchecked" if auto_unchecked else None
        ok, key = self._validate_plan()
        if ok:
            self._set_stage(
                "stage.ready_hint",
                note_key=note_key,
                count=len(self.audio_files),
                actions=self._actions_text(),
            )
        else:
            self._set_stage(key, note_key=note_key)
        self.btn_start.config(state=tk.NORMAL if ok else tk.DISABLED)

    def _show_selection(self, var, label, path, as_basename=False):
        """在标签上显示当前选择（有值走词条占位符，空值显示「未选择」）。"""
        if path:
            self.set_text(var, "label.basename" if as_basename else "label.path",
                          name=os.path.basename(path), path=path)
            label.config(fg="#4AF626")
        else:
            self.set_text(var, "label.unselected")
            label.config(fg="#A9A9A9")

    def _restore_saved_selection(self):
        saved_image = self.cfg.get("image_path", "")
        if saved_image and os.path.isfile(saved_image):
            self.image_path = saved_image
            self._show_selection(self.img_var, self.lbl_img, saved_image,
                                 as_basename=True)
        saved_out = self.cfg.get("output_dir", "")
        if saved_out and os.path.isdir(saved_out):
            self.output_dir = saved_out
            self._show_selection(self.dir_var, self.lbl_dir, saved_out)
        self._sync_options()

    # ---------- 界面 ----------
    def _group(self, key):
        """带边框的分组容器，返回可放行的内层 Frame（按词条 key 登记）。"""
        title_var = tk.StringVar()
        self.set_text(title_var, key)
        inner = widgets.group(self.root, title_var=title_var)
        self.groups[key] = inner
        return inner

    @staticmethod
    def _row(parent):
        return widgets.row(parent)

    def _caption(self, parent, key):
        var = tk.StringVar()
        self.set_text(var, key)
        return widgets.caption(parent, textvariable=var)

    def _check(self, parent, key, variable):
        var = tk.StringVar()
        self.set_text(var, key)
        return widgets.checkbutton(parent, variable=variable, textvariable=var,
                                   command=self._on_option_change)

    def setup_ui(self):
        # --- FFmpeg 状态栏 + 语言下拉（同一行，语言靠右） ---
        engine_frame = tk.Frame(self.root, bg="#252526", pady=8)
        engine_frame.pack(fill="x", padx=0, pady=(0, 4))

        tk.Label(engine_frame, textvariable=self.engine_prefix_var, bg="#252526",
                 fg="#CCCCCC", font=("Microsoft YaHei", 9, "bold")).pack(
            side="left", padx=(20, 0))
        self.lbl_engine = tk.Label(engine_frame, textvariable=self.engine_var, bg="#252526",
                                   fg="#A9A9A9", font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_engine.pack(side="left", fill="x", expand=True, padx=8)

        # 先 pack 的靠最右：下拉框在最右，其左侧是「界面语言」标签
        self.cmb_language = ttk.Combobox(
            engine_frame, textvariable=self.lang_display_var, state="readonly",
            values=[name for _code, name in SUPPORTED_LANGUAGES], width=12,
            font=("Microsoft YaHei", 9))
        self.cmb_language.pack(side="right", padx=(0, 16))
        self.cmb_language.bind("<<ComboboxSelected>>", self._on_language_pick)
        tk.Label(engine_frame, textvariable=self.lang_label_var, bg="#252526",
                 fg="#CCCCCC", font=("Microsoft YaHei", 9)).pack(
            side="right", padx=(8, 4))

        self.btn_engine = tk.Button(engine_frame, textvariable=self._var_for("btn.change_ffmpeg"),
                                    font=("Microsoft YaHei", 9),
                                    bg="#3C3C3C", fg="white", relief="flat", width=6,
                                    command=self.choose_ffmpeg)
        self.btn_engine.pack(side="right", padx=(0, 6))
        self.btn_redetect = tk.Button(
            engine_frame, textvariable=self._var_for("btn.redetect"),
            font=("Microsoft YaHei", 9), bg="#3C3C3C", fg="white", relief="flat", width=9,
            command=self.refresh_ffmpeg)
        self.btn_redetect.pack(side="right", padx=(0, 6))

        # --- 输入音频 ---
        grp_in = self._group("group.input")
        row = self._row(grp_in)
        self._caption(row, "label.audio").pack(side="left")
        self.btn_audio = tk.Button(row, textvariable=self._var_for("btn.select_audio"),
                                   font=("Microsoft YaHei", 9, "bold"),
                                   bg="#007ACC", fg="white", activebackground="#005A9E",
                                   activeforeground="white", width=14, relief="flat",
                                   command=self.select_audio)
        self.btn_audio.pack(side="left")
        self.lbl_audio = tk.Label(row, textvariable=self.audio_var, bg="#252526",
                                  fg="#A9A9A9", font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_audio.pack(side="left", padx=12)

        # --- 选项 A · 降噪 ---
        grp_a = self._group("group.options_a")
        row = self._row(grp_a)
        self._caption(row, "label.denoise").pack(side="left")
        self.cmb_denoise = self._make_combo(row, DENOISE_OPTIONS, self.denoise_var,
                                            width=22)
        self.cmb_denoise.pack(side="left")

        # --- 选项 B · 识别与字幕 ---
        grp_b = self._group("group.options_b")
        row = self._row(grp_b)
        self._caption(row, "label.model").pack(side="left")
        self.cmb_model = self._make_combo(row, STT_MODEL_OPTIONS, self.stt_model_var,
                                          width=30)
        self.cmb_model.pack(side="left", padx=(0, 18))
        self._caption(row, "label.language").pack(side="left")
        self.cmb_lang = self._make_combo(row, STT_LANG_OPTIONS, self.stt_lang_var,
                                         width=16)
        self.cmb_lang.pack(side="left")

        row = self._row(grp_b)
        self._caption(row, "label.subtitle").pack(side="left")
        self.chk_srt = self._check(row, "chk.srt", self.srt_var)
        self.chk_srt.pack(side="left")
        self.chk_txt = self._check(row, "chk.txt", self.txt_var)
        self.chk_txt.pack(side="left", padx=(16, 0))

        # --- 选项 C · 视频生成 ---
        grp_c = self._group("group.options_c")
        row = self._row(grp_c)
        self.chk_mux_original = self._check(
            row, "chk.mux_original", self.mux_original_var)
        self.chk_mux_original.pack(side="left")

        row = self._row(grp_c)
        self.chk_mux_denoised = self._check(
            row, "chk.mux_denoised", self.mux_denoised_var)
        self.chk_mux_denoised.pack(side="left")

        row = self._row(grp_c)
        self._caption(row, "label.cover").pack(side="left")
        self.btn_img = tk.Button(row, textvariable=self._var_for("btn.select_cover"),
                                 font=("Microsoft YaHei", 9, "bold"),
                                 bg="#D97706", fg="white", activebackground="#B45309",
                                 activeforeground="white", width=14, relief="flat",
                                 command=self.select_image)
        self.btn_img.pack(side="left")
        self.lbl_img = tk.Label(row, textvariable=self.img_var, bg="#252526", fg="#A9A9A9",
                                font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_img.pack(side="left", padx=12)

        row = self._row(grp_c)
        self._caption(row, "label.size").pack(side="left")
        self.cmb_size = self._make_combo(row, SIZE_OPTIONS, self.size_var, width=24)
        self.cmb_size.pack(side="left")
        tk.Label(row, textvariable=self._var_for("label.size_hint"), bg="#252526",
                 fg="#777777", font=("Microsoft YaHei", 8)).pack(side="left", padx=10)

        # --- 输出目录 ---
        grp_out = self._group("group.output")
        row = self._row(grp_out)
        self._caption(row, "label.output_dir").pack(side="left")
        self.btn_dir = tk.Button(row, textvariable=self._var_for("btn.select_dir"),
                                 font=("Microsoft YaHei", 9, "bold"),
                                 bg="#8B5CF6", fg="white", activebackground="#7C3AED",
                                 activeforeground="white", width=14, relief="flat",
                                 command=self.select_directory)
        self.btn_dir.pack(side="left")
        self.lbl_dir = tk.Label(row, textvariable=self.dir_var, bg="#252526", fg="#A9A9A9",
                                font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_dir.pack(side="left", padx=12)

        # --- 执行区 ---
        exec_row = tk.Frame(self.root, bg="#1E1E1E")
        exec_row.pack(fill="x", padx=20, pady=(0, 6))
        self.btn_start = tk.Button(exec_row, textvariable=self.start_var,
                                   font=("Microsoft YaHei", 10, "bold"),
                                   bg="#10B981", fg="white", activebackground="#059669",
                                   activeforeground="white", disabledforeground="#9CA3AF",
                                   relief="flat", width=22, height=2, cursor="hand2",
                                   command=self.start_processing)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.btn_cancel = tk.Button(exec_row, textvariable=self._var_for("btn.cancel"),
                                    font=("Microsoft YaHei", 10, "bold"),
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

        self.log(t("log.welcome", title=t("app.title"), version=APP_VERSION))
        self.log(t("log.render_info"))
        self.log(t("log.formats",
                   formats=" / ".join(ext.lstrip(".").upper() for ext in AUDIO_EXTS[:10])))
        if module_available("faster_whisper"):
            self.log(t("log.asr_ready"))
        else:
            self.log(t("log.asr_missing"), is_error=True)
        if module_available("sherpa_onnx"):
            self.log(t("log.denoise_ready"))
        else:
            self.log(t("log.denoise_partial"))
        # 初始化阶段记录的配置回退告警（此时日志控件已就绪）
        for warning in self._startup_warnings:
            self.log(warning, is_error=True)
        self._startup_warnings.clear()
        self._sync_options()

    def _var_for(self, key, **kwargs):
        """快捷构造：创建 StringVar 并登记词条（控件直接绑定）。"""
        var = tk.StringVar()
        self.set_text(var, key, **kwargs)
        return var

    # ---------- 日志 / 进度 ----------
    def log(self, text, is_error=False):
        """写入已翻译好的文本；历史内容不随语言切换回译。"""
        self.root.after(0, self._insert_text, text, is_error)

    def _insert_text(self, text, is_error):
        self.text_area.insert(tk.END, text, "error" if is_error else "normal")
        self.text_area.see(tk.END)

    def set_progress(self, value):
        self.root.after(0, lambda: self.progress_var.set(max(0.0, min(100.0, value))))

    def set_stage(self, text):
        """pipeline 回调：text 已在生成时翻译，无法回译（故清空 key 记录）。"""
        self._stage_key = None
        self._stage_kwargs = {}
        self._stage_note_key = None
        self.root.after(0, lambda: self.stage_var.set(text))

    # ---------- 引擎 ----------
    def _refresh_engine_label(self):
        if self._engine_state == "ok" and self.ffmpeg_text:
            self.engine_var.set(self.ffmpeg_text)
            self.lbl_engine.config(fg="#4AF626")
        elif self._engine_state == "missing":
            self.engine_var.set(t("engine.not_found"))
            self.lbl_engine.config(fg="#FF4500")
        else:
            self.engine_var.set(t("engine.detecting"))
            self.lbl_engine.config(fg="#A9A9A9")

    def refresh_ffmpeg(self):
        saved = self.cfg.get("ffmpeg_path") or ""
        usable, rejected = discover_ffmpeg(saved)
        if usable:
            # 已保存的路径若仍可用则优先保留，避免「重新检测」覆盖用户手动指定的引擎
            kept = self._find_usable(saved, usable)
            best = kept or usable[0]
            self.ffmpeg_path = best["path"]
            ver = best["version"].replace("ffmpeg version", "").strip()
            short = ver.split("Copyright")[0].strip()[:60]
            self.ffmpeg_text = f"{best['path']}  ({short})"
            self._engine_state = "ok"
            self._refresh_engine_label()
            if kept:
                self.log(t("log.ffmpeg_kept", path=kept["path"]))
            self.log(t("log.ffmpeg_enabled", info=self.ffmpeg_text))
            if rejected:
                self.log(t("log.ffmpeg_skipped",
                           dirs="; ".join(os.path.dirname(r["path"]) for r in rejected)))
            self._persist_path_only()
        else:
            self.ffmpeg_path = ""
            self._engine_state = "missing"
            self._refresh_engine_label()
            self.log(t("log.ffmpeg_none"), is_error=True)
            if rejected:
                self.log(t("log.ffmpeg_rejected_header"), is_error=True)
                for r in rejected:
                    self.log(t("log.ffmpeg_rejected_item",
                               path=r["path"], libx264=r["libx264"], aac=r["aac"]),
                             is_error=True)

    @staticmethod
    def _find_usable(saved, usable):
        """在探测结果中找回已保存的路径（忽略大小写与斜杠差异）。"""
        if not saved:
            return None
        target = os.path.normcase(os.path.normpath(saved))
        for info in usable:
            if os.path.normcase(os.path.normpath(info["path"])) == target:
                return info
        return None

    def _persist_path_only(self):
        if self.ffmpeg_path and self.cfg.get("ffmpeg_path") != self.ffmpeg_path:
            self.cfg["ffmpeg_path"] = self.ffmpeg_path
            save_config(self.cfg)

    def choose_ffmpeg(self):
        path = filedialog.askopenfilename(
            title=t("dlg.pick_ffmpeg"),
            filetypes=[("ffmpeg", "ffmpeg.exe"), (t("filetype.all_files"), "*.*")])
        if not path:
            return
        info = ffmpeg_info(path)
        if not info:
            messagebox.showerror(t("dlg.ffmpeg_invalid_title"), t("dlg.ffmpeg_invalid_msg"))
            return
        if not (info["libx264"] and info["aac"]):
            messagebox.showerror(
                t("dlg.ffmpeg_missing_enc_title"),
                t("dlg.ffmpeg_missing_enc_msg",
                  libx264=info["libx264"], aac=info["aac"]),
            )
            return
        self.ffmpeg_path = path
        self.ffmpeg_text = f"{path}  ({info['version'].split('Copyright')[0].strip()[:60]})"
        self._engine_state = "ok"
        self._refresh_engine_label()
        self._persist_path_only()
        self.log(t("log.ffmpeg_manual", path=path))

    # ---------- 选择文件 ----------
    def select_audio(self):
        files = filedialog.askopenfilenames(
            title=t("dlg.pick_audio"), filetypes=audio_filetypes())
        if not files:
            return
        self.audio_files = list(files)
        self.set_text(self.audio_var, "label.audio_selected", count=len(self.audio_files))
        self.lbl_audio.config(fg="#4AF626")
        self.log(t("log.audio_imported", count=len(self.audio_files)))
        if not self.output_dir:
            first_dir = os.path.dirname(self.audio_files[0])
            self.output_dir = first_dir
            self._show_selection(self.dir_var, self.lbl_dir, first_dir)
            self.log(t("log.output_auto", dir=first_dir))
        self._persist()
        self._sync_options()

    def select_image(self):
        path = filedialog.askopenfilename(title=t("dlg.pick_cover"),
                                          filetypes=image_filetypes())
        if not path:
            return
        self.image_path = path
        self._show_selection(self.img_var, self.lbl_img, path, as_basename=True)
        self.log(t("log.cover_ready", name=os.path.basename(path)))
        self._persist()
        self._sync_options()

    def select_directory(self):
        directory = filedialog.askdirectory(title=t("dlg.pick_output_dir"))
        if not directory:
            return
        self.output_dir = directory
        self._show_selection(self.dir_var, self.lbl_dir, directory)
        self.log(t("log.output_set", dir=directory))
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
            self.set_text(self.start_var, "btn.start_busy")
            self.btn_start.config(state=tk.DISABLED)
            self.btn_cancel.config(state=tk.NORMAL)
        else:
            self.set_text(self.start_var, "btn.start")
            self.btn_cancel.config(state=tk.DISABLED)
            self._sync_options()

    def _build_plan(self):
        """在主线程一次性读完全部 Tk 变量，打包成 JobPlan 交给工作线程。

        Tk 变量里存的是内部值，这里直接透传，不再做文案 → 值反查。
        """
        return build_plan(
            audio_files=self.audio_files,
            output_dir=self.output_dir,
            image_path=self.image_path,
            size_mode=self.size_var.get(),
            model_code=self.stt_model_var.get(),
            denoise_code=self.denoise_var.get(),
            lang_code=self.stt_lang_var.get(),
            srt=bool(self.srt_var.get()),
            txt=bool(self.txt_var.get()),
            mux_original=bool(self.mux_original_var.get()),
            mux_denoised=bool(self.mux_denoised_var.get()),
            ffmpeg_path=self.ffmpeg_path,
        )

    def start_processing(self):
        if not self.ffmpeg_path:
            messagebox.showwarning(t("dlg.no_ffmpeg_title"), t("dlg.no_ffmpeg_msg"))
            self.choose_ffmpeg()
            return

        ok, key = self._validate_plan()
        if not ok:
            self._set_stage(key)
            return

        # 未指定输出目录时回退到第一个音频所在目录（沿用旧行为）
        if not self.output_dir:
            self.output_dir = os.path.dirname(self.audio_files[0])
            self._show_selection(self.dir_var, self.lbl_dir, self.output_dir)
            self.log(t("log.output_fallback", dir=self.output_dir))

        plan = self._build_plan()
        if plan.need_stt and not module_available("faster_whisper"):
            messagebox.showerror(
                t("dlg.missing_asr_title"),
                t("dlg.missing_asr_msg", exe=sys.executable),
            )
            return

        self._stop = False
        self._proc = None
        self.progress_var.set(0)
        self.lock_ui(True)

        tasks = []
        if plan.only_denoise:
            tasks.append(t("act.only_denoise"))
        if plan.need_stt:
            formats = " / ".join(
                [name for name, on in (("SRT", plan.srt), ("TXT", plan.txt)) if on])
            tasks.append(t("task.subtitle", formats=formats))
        if plan.mux_original:
            tasks.append(t("task.mux_original"))
        if plan.mux_denoised:
            tasks.append(t("task.mux_denoised"))

        self.log(LOG_TASK_HEADER)
        self.log(t("log.output_dir", dir=plan.output_dir))
        self.log(t("log.denoise_model_line",
                   denoise=denoise_desc(plan.denoise_mode),
                   model=plan.model_name or t("label.off")))
        self.log(t("log.tasks", tasks=" + ".join(tasks)))
        if plan.need_stt and not whisper_model_ready(plan.model_name):
            self.log(t("log.first_model", model=plan.model_name))
        self.log(t("log.start", count=len(plan.audio_files)))

        pipeline = Pipeline(
            plan,
            log=self.log,
            set_progress=self.set_progress,
            set_stage=self.set_stage,
            should_stop=lambda: self._stop,
            on_proc=self._set_proc,
            on_done=lambda: self.root.after(0, self._finish_ui),
        )
        threading.Thread(target=pipeline.run, daemon=True).start()

    def cancel_processing(self):
        self._stop = True
        self._set_stage("stage.cancelling")
        self.log(t("log.cancel_request"), is_error=True)
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _set_proc(self, proc):
        """ffmpeg 子进程句柄回调，取消按钮据此真正 terminate。"""
        self._proc = proc

    def _finish_ui(self):
        self.lock_ui(False)
        self._set_stage("stage.cancelled" if self._stop else "stage.done")

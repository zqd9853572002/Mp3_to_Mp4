# -*- coding: utf-8 -*-
"""主窗口：布局、联动置灰、文件选择、配置持久化、日志/进度与线程启动。

业务执行全部交给 `pipeline.Pipeline`，本模块不直接调用 ffmpeg/asr 函数。
所有用户可见文案均从 `ui.texts` 引用。
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from ..asr import whisper_model_ready
from ..config import (
    APP_TITLE,
    APP_VERSION,
    AUDIO_EXTS,
    AUDIO_FILETYPES,
    DEFAULT_DENOISE,
    DEFAULT_MODE,
    DEFAULT_STT_LANG,
    DEFAULT_STT_MODEL,
    DENOISE_MODES,
    IMAGE_FILETYPES,
    SIZE_MODES,
    STT_LANGS,
    STT_MODELS,
    legacy_subtitle_flags,
    load_config,
    module_available,
    save_config,
)
from ..ffmpeg import discover_ffmpeg, ffmpeg_info
from ..pipeline import Pipeline, build_plan, denoise_desc, option_flags
from . import texts, widgets


class AudioToVideoApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(texts.WINDOW_TITLE.format(title=APP_TITLE, version=APP_VERSION))
        self.root.geometry("980x940")
        self.root.minsize(960, 900)
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

        # 旧配置（v4.0）只有一个 stt_enabled：等于「同时生成两种格式」
        srt_default, txt_default = legacy_subtitle_flags(self.cfg)

        self.size_var = tk.StringVar(value=self._label_from_mode(self.cfg.get("size_mode", DEFAULT_MODE)))
        self.progress_var = tk.DoubleVar(value=0.0)
        self.stage_var = tk.StringVar(value=texts.STAGE_READY)

        self.stt_model_var = tk.StringVar(value=self._label_from_value(
            STT_MODELS, self.cfg.get("stt_model", DEFAULT_STT_MODEL)))
        self.stt_lang_var = tk.StringVar(value=self._label_from_value(
            STT_LANGS, self.cfg.get("stt_language", DEFAULT_STT_LANG)))
        self.denoise_var = tk.StringVar(value=self._label_from_value(
            DENOISE_MODES, self.cfg.get("denoise_mode", DEFAULT_DENOISE)))
        self.srt_var = tk.BooleanVar(value=srt_default)
        self.txt_var = tk.BooleanVar(value=txt_default)
        self.mux_original_var = tk.BooleanVar(value=bool(self.cfg.get("mux_original", False)))
        self.mux_denoised_var = tk.BooleanVar(value=bool(self.cfg.get("mux_denoised", False)))

        self.setup_ui()
        self._restore_saved_selection()
        self.root.after(100, self.refresh_ffmpeg)

    # ---------- 配置辅助 ----------
    @staticmethod
    def _label_from_mode(mode: str) -> str:
        for label, value in SIZE_MODES.items():
            if value == mode:
                return label
        return next(k for k, v in SIZE_MODES.items() if v == DEFAULT_MODE)

    @staticmethod
    def _label_from_value(mapping: dict, value) -> str:
        for label, val in mapping.items():
            if val == value:
                return label
        return next(iter(mapping))

    def _persist(self):
        self.cfg.update({
            "ffmpeg_path": self.ffmpeg_path,
            "image_path": self.image_path,
            "output_dir": self.output_dir,
            "size_mode": SIZE_MODES.get(self.size_var.get(), DEFAULT_MODE),
            "stt_model": STT_MODELS.get(self.stt_model_var.get(), DEFAULT_STT_MODEL),
            "stt_language": STT_LANGS.get(self.stt_lang_var.get(), DEFAULT_STT_LANG),
            "denoise_mode": DENOISE_MODES.get(self.denoise_var.get(), DEFAULT_DENOISE),
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
            STT_MODELS.get(self.stt_model_var.get(), DEFAULT_STT_MODEL),
            DENOISE_MODES.get(self.denoise_var.get(), DEFAULT_DENOISE),
            self.srt_var.get(),
            self.txt_var.get(),
            self.mux_original_var.get(),
            self.mux_denoised_var.get(),
        )

    def _validate_plan(self):
        """返回 (是否可执行, 中性阶段提示)。"""
        flags = self._option_flags()
        if not self.audio_files:
            return False, texts.VALIDATE_NO_AUDIO
        if not (flags["need_stt"] or flags["mux_original"]
                or flags["mux_denoised"] or flags["only_denoise"]):
            return False, texts.VALIDATE_NO_ACTION
        if (flags["mux_original"] or flags["mux_denoised"]) and not self.image_path:
            return False, texts.VALIDATE_NEED_COVER
        acts = []
        if flags["only_denoise"]:
            acts.append(texts.ACT_ONLY_DENOISE)
        if flags["need_stt"]:
            acts.append(texts.ACT_SUBTITLE)
        if flags["mux_original"]:
            acts.append(texts.ACT_MUX_ORIGINAL)
        if flags["mux_denoised"]:
            acts.append(texts.ACT_MUX_DENOISED)
        return True, texts.STAGE_READY_HINT.format(
            count=len(self.audio_files), actions=" + ".join(acts))

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

        # 降噪 = 关闭 → 降噪 MP4 置灰（保留原勾选，恢复时自动还原）
        self.chk_mux_denoised.config(
            state=tk.NORMAL if flags["denoise_on"] else tk.DISABLED)

        # 封面按钮：没有视频输出时灰色但仍可点击，方便提前准备素材
        if flags["mux_original"] or flags["mux_denoised"]:
            self.btn_img.config(bg="#D97706", fg="white", activebackground="#B45309",
                                activeforeground="white", cursor="hand2")
        else:
            self.btn_img.config(bg="#4A4A4A", fg="#9A9A9A", activebackground="#4A4A4A",
                                activeforeground="#9A9A9A", cursor="hand2")

        ok, hint = self._validate_plan()
        self.btn_start.config(state=tk.NORMAL if ok else tk.DISABLED)
        self.stage_var.set(hint)

    def _restore_saved_selection(self):
        saved_image = self.cfg.get("image_path", "")
        if saved_image and os.path.isfile(saved_image):
            self.image_path = saved_image
            self.lbl_img.config(text=os.path.basename(saved_image), fg="#4AF626")
        saved_out = self.cfg.get("output_dir", "")
        if saved_out and os.path.isdir(saved_out):
            self.output_dir = saved_out
            self.lbl_dir.config(text=saved_out, fg="#4AF626")
        self._sync_options()

    # ---------- 界面 ----------
    def _group(self, title):
        """带边框的分组容器，返回可放行的内层 Frame。"""
        return widgets.group(self.root, title)

    @staticmethod
    def _row(parent):
        return widgets.row(parent)

    @staticmethod
    def _caption(parent, text):
        return widgets.caption(parent, text)

    def setup_ui(self):
        # --- FFmpeg 状态栏 ---
        engine_frame = tk.Frame(self.root, bg="#252526", pady=8)
        engine_frame.pack(fill="x", padx=0, pady=(0, 4))

        tk.Label(engine_frame, text=texts.LBL_ENGINE_PREFIX, bg="#252526", fg="#CCCCCC",
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left", padx=(20, 0))
        self.lbl_engine = tk.Label(engine_frame, text=texts.TXT_ENGINE_DETECTING, bg="#252526",
                                   fg="#A9A9A9", font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_engine.pack(side="left", fill="x", expand=True, padx=8)

        self.btn_engine = tk.Button(engine_frame, text=texts.BTN_ENGINE_CHANGE,
                                    font=("Microsoft YaHei", 9),
                                    bg="#3C3C3C", fg="white", relief="flat", width=6,
                                    command=self.choose_ffmpeg)
        self.btn_engine.pack(side="right", padx=(0, 6))
        self.btn_redetect = tk.Button(engine_frame, text=texts.BTN_ENGINE_REDETECT,
                                      font=("Microsoft YaHei", 9),
                                      bg="#3C3C3C", fg="white", relief="flat", width=9,
                                      command=self.refresh_ffmpeg)
        self.btn_redetect.pack(side="right", padx=(0, 6))

        # --- 输入音频 ---
        grp_in = self._group(texts.GROUP_INPUT)
        row = self._row(grp_in)
        self._caption(row, texts.CAPTION_AUDIO).pack(side="left")
        self.btn_audio = tk.Button(row, text=texts.BTN_SELECT_AUDIO,
                                   font=("Microsoft YaHei", 9, "bold"),
                                   bg="#007ACC", fg="white", activebackground="#005A9E",
                                   activeforeground="white", width=14, relief="flat",
                                   command=self.select_audio)
        self.btn_audio.pack(side="left")
        self.lbl_audio = tk.Label(row, text=texts.TXT_NOT_SELECTED, bg="#252526", fg="#A9A9A9",
                                  font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_audio.pack(side="left", padx=12)

        # --- 选项 A · 音频与文字 ---
        grp_a = self._group(texts.GROUP_OPTIONS_A)
        row = self._row(grp_a)
        self._caption(row, texts.CAPTION_DENOISE).pack(side="left")
        self.cmb_denoise = ttk.Combobox(row, textvariable=self.denoise_var, state="readonly",
                                        values=list(DENOISE_MODES.keys()), width=22,
                                        font=("Microsoft YaHei", 9))
        self.cmb_denoise.pack(side="left")
        self.cmb_denoise.bind("<<ComboboxSelected>>", self._on_option_change)

        row = self._row(grp_a)
        self._caption(row, texts.CAPTION_MODEL).pack(side="left")
        self.cmb_model = ttk.Combobox(row, textvariable=self.stt_model_var, state="readonly",
                                      values=list(STT_MODELS.keys()), width=30,
                                      font=("Microsoft YaHei", 9))
        self.cmb_model.pack(side="left", padx=(0, 18))
        self.cmb_model.bind("<<ComboboxSelected>>", self._on_option_change)
        self._caption(row, texts.CAPTION_LANG).pack(side="left")
        self.cmb_lang = ttk.Combobox(row, textvariable=self.stt_lang_var, state="readonly",
                                     values=list(STT_LANGS.keys()), width=16,
                                     font=("Microsoft YaHei", 9))
        self.cmb_lang.pack(side="left")
        self.cmb_lang.bind("<<ComboboxSelected>>", self._on_option_change)

        row = self._row(grp_a)
        self._caption(row, texts.CAPTION_SUBTITLE).pack(side="left")
        self.chk_srt = widgets.checkbutton(row, texts.CHK_SRT, self.srt_var,
                                           command=self._on_option_change)
        self.chk_srt.pack(side="left")
        self.chk_txt = widgets.checkbutton(row, texts.CHK_TXT, self.txt_var,
                                           command=self._on_option_change)
        self.chk_txt.pack(side="left", padx=(16, 0))

        # --- 选项 B · 视频生成 ---
        grp_b = self._group(texts.GROUP_OPTIONS_B)
        row = self._row(grp_b)
        self.chk_mux_original = widgets.checkbutton(
            row, texts.CHK_MUX_ORIGINAL, self.mux_original_var,
            command=self._on_option_change)
        self.chk_mux_original.pack(side="left")

        row = self._row(grp_b)
        self.chk_mux_denoised = widgets.checkbutton(
            row, texts.CHK_MUX_DENOISED, self.mux_denoised_var,
            command=self._on_option_change)
        self.chk_mux_denoised.pack(side="left")

        row = self._row(grp_b)
        self._caption(row, texts.CAPTION_COVER).pack(side="left")
        self.btn_img = tk.Button(row, text=texts.BTN_SELECT_COVER,
                                 font=("Microsoft YaHei", 9, "bold"),
                                 bg="#D97706", fg="white", activebackground="#B45309",
                                 activeforeground="white", width=14, relief="flat",
                                 command=self.select_image)
        self.btn_img.pack(side="left")
        self.lbl_img = tk.Label(row, text=texts.TXT_NOT_SELECTED, bg="#252526", fg="#A9A9A9",
                                font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_img.pack(side="left", padx=12)

        row = self._row(grp_b)
        self._caption(row, texts.CAPTION_SIZE).pack(side="left")
        self.cmb_size = ttk.Combobox(row, textvariable=self.size_var, state="readonly",
                                     values=list(SIZE_MODES.keys()), width=24,
                                     font=("Microsoft YaHei", 9))
        self.cmb_size.pack(side="left")
        self.cmb_size.bind("<<ComboboxSelected>>", self._on_option_change)
        tk.Label(row, text=texts.LBL_SIZE_HINT, bg="#252526", fg="#777777",
                 font=("Microsoft YaHei", 8)).pack(side="left", padx=10)

        # --- 输出目录 ---
        grp_out = self._group(texts.GROUP_OUTPUT)
        row = self._row(grp_out)
        self._caption(row, texts.CAPTION_OUTPUT_DIR).pack(side="left")
        self.btn_dir = tk.Button(row, text=texts.BTN_SELECT_OUTPUT_DIR,
                                 font=("Microsoft YaHei", 9, "bold"),
                                 bg="#8B5CF6", fg="white", activebackground="#7C3AED",
                                 activeforeground="white", width=14, relief="flat",
                                 command=self.select_directory)
        self.btn_dir.pack(side="left")
        self.lbl_dir = tk.Label(row, text=texts.TXT_NOT_SELECTED, bg="#252526", fg="#A9A9A9",
                                font=("Microsoft YaHei", 9), anchor="w")
        self.lbl_dir.pack(side="left", padx=12)

        # --- 执行区 ---
        exec_row = tk.Frame(self.root, bg="#1E1E1E")
        exec_row.pack(fill="x", padx=20, pady=(0, 6))
        self.btn_start = tk.Button(exec_row, text=texts.BTN_START,
                                   font=("Microsoft YaHei", 10, "bold"),
                                   bg="#10B981", fg="white", activebackground="#059669",
                                   activeforeground="white", disabledforeground="#9CA3AF",
                                   relief="flat", width=22, height=2, cursor="hand2",
                                   command=self.start_processing)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.btn_cancel = tk.Button(exec_row, text=texts.BTN_CANCEL,
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

        self.log(texts.LOG_WELCOME.format(title=APP_TITLE, version=APP_VERSION))
        self.log(texts.LOG_RENDER_INFO)
        self.log(texts.LOG_FORMATS.format(
            formats=" / ".join(e.lstrip(".").upper() for e in AUDIO_EXTS[:10])))
        if module_available("faster_whisper"):
            self.log(texts.LOG_ASR_READY)
        else:
            self.log(texts.LOG_ASR_MISSING, is_error=True)
        if module_available("sherpa_onnx"):
            self.log(texts.LOG_DENOISE_READY)
        else:
            self.log(texts.LOG_DENOISE_PARTIAL)
        self._sync_options()

    # ---------- 日志 / 进度 ----------
    def log(self, text, is_error=False):
        self.root.after(0, self._insert_text, text, is_error)

    def _insert_text(self, text, is_error):
        self.text_area.insert(tk.END, text, "error" if is_error else "normal")
        self.text_area.see(tk.END)

    def set_progress(self, value):
        self.root.after(0, lambda: self.progress_var.set(max(0.0, min(100.0, value))))

    def set_stage(self, text):
        self.root.after(0, lambda: self.stage_var.set(text))

    # ---------- 引擎 ----------
    def refresh_ffmpeg(self):
        saved = self.cfg.get("ffmpeg_path")
        usable, rejected = discover_ffmpeg(saved)
        if usable:
            best = usable[0]
            self.ffmpeg_path = best["path"]
            ver = best["version"].replace("ffmpeg version", "").strip()
            short = ver.split("Copyright")[0].strip()[:60]
            self.ffmpeg_text = f"{best['path']}  ({short})"
            self.lbl_engine.config(text=self.ffmpeg_text, fg="#4AF626")
            self.log(texts.LOG_FFMPEG_ENABLED.format(info=self.ffmpeg_text))
            if rejected:
                self.log(texts.LOG_FFMPEG_SKIPPED.format(
                    dirs="; ".join(os.path.dirname(r["path"]) for r in rejected)))
            self._persist_path_only()
        else:
            self.ffmpeg_path = ""
            self.lbl_engine.config(text=texts.TXT_ENGINE_NOT_FOUND, fg="#FF4500")
            self.log(texts.LOG_FFMPEG_NONE, is_error=True)
            if rejected:
                self.log(texts.LOG_FFMPEG_REJECTED_HEADER, is_error=True)
                for r in rejected:
                    self.log(texts.LOG_FFMPEG_REJECTED_ITEM.format(
                        path=r["path"], libx264=r["libx264"], aac=r["aac"]), is_error=True)

    def _persist_path_only(self):
        if self.ffmpeg_path and self.cfg.get("ffmpeg_path") != self.ffmpeg_path:
            self.cfg["ffmpeg_path"] = self.ffmpeg_path
            save_config(self.cfg)

    def choose_ffmpeg(self):
        path = filedialog.askopenfilename(
            title=texts.DLG_PICK_FFMPEG,
            filetypes=[("ffmpeg", "ffmpeg.exe"), (texts.FILETYPE_ALL_FILES, "*.*")])
        if not path:
            return
        info = ffmpeg_info(path)
        if not info:
            messagebox.showerror(texts.DLG_FFMPEG_INVALID_TITLE, texts.DLG_FFMPEG_INVALID_MSG)
            return
        if not (info["libx264"] and info["aac"]):
            messagebox.showerror(
                texts.DLG_FFMPEG_MISSING_ENC_TITLE,
                texts.DLG_FFMPEG_MISSING_ENC_MSG.format(
                    libx264=info["libx264"], aac=info["aac"]),
            )
            return
        self.ffmpeg_path = path
        self.ffmpeg_text = f"{path}  ({info['version'].split('Copyright')[0].strip()[:60]})"
        self.lbl_engine.config(text=self.ffmpeg_text, fg="#4AF626")
        self._persist_path_only()
        self.log(texts.LOG_FFMPEG_MANUAL.format(path=path))

    # ---------- 选择文件 ----------
    def select_audio(self):
        files = filedialog.askopenfilenames(
            title=texts.DLG_PICK_AUDIO, filetypes=AUDIO_FILETYPES)
        if not files:
            return
        self.audio_files = list(files)
        self.lbl_audio.config(
            text=texts.TXT_AUDIO_SELECTED.format(count=len(self.audio_files)), fg="#4AF626")
        self.log(texts.LOG_AUDIO_IMPORTED.format(count=len(self.audio_files)))
        if not self.output_dir:
            first_dir = os.path.dirname(self.audio_files[0])
            self.output_dir = first_dir
            self.lbl_dir.config(text=first_dir, fg="#4AF626")
            self.log(texts.LOG_OUTPUT_AUTO.format(dir=first_dir))
        self._persist()
        self._sync_options()

    def select_image(self):
        path = filedialog.askopenfilename(title=texts.DLG_PICK_COVER, filetypes=IMAGE_FILETYPES)
        if not path:
            return
        self.image_path = path
        self.lbl_img.config(text=os.path.basename(path), fg="#4AF626")
        self.log(texts.LOG_COVER_READY.format(name=os.path.basename(path)))
        self._persist()
        self._sync_options()

    def select_directory(self):
        directory = filedialog.askdirectory(title=texts.DLG_PICK_OUTPUT_DIR)
        if not directory:
            return
        self.output_dir = directory
        self.lbl_dir.config(text=directory, fg="#4AF626")
        self.log(texts.LOG_OUTPUT_SET.format(dir=directory))
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
            self.btn_start.config(state=tk.DISABLED, text=texts.BTN_START_BUSY)
            self.btn_cancel.config(state=tk.NORMAL)
        else:
            self.btn_start.config(text=texts.BTN_START)
            self.btn_cancel.config(state=tk.DISABLED)
            self._sync_options()

    def _build_plan(self):
        """在主线程一次性读完全部 Tk 变量，打包成 JobPlan 交给工作线程。"""
        return build_plan(
            audio_files=self.audio_files,
            output_dir=self.output_dir,
            image_path=self.image_path,
            size_label=self.size_var.get(),
            model_code=STT_MODELS.get(self.stt_model_var.get(), DEFAULT_STT_MODEL),
            denoise_code=DENOISE_MODES.get(self.denoise_var.get(), DEFAULT_DENOISE),
            lang_code=STT_LANGS.get(self.stt_lang_var.get(), DEFAULT_STT_LANG),
            srt=bool(self.srt_var.get()),
            txt=bool(self.txt_var.get()),
            mux_original=bool(self.mux_original_var.get()),
            mux_denoised=bool(self.mux_denoised_var.get()),
            ffmpeg_path=self.ffmpeg_path,
        )

    def start_processing(self):
        if not self.ffmpeg_path:
            messagebox.showwarning(texts.DLG_NO_FFMPEG_TITLE, texts.DLG_NO_FFMPEG_MSG)
            self.choose_ffmpeg()
            return

        ok, hint = self._validate_plan()
        if not ok:
            self.stage_var.set(hint)
            return

        # 未指定输出目录时回退到第一个音频所在目录（沿用旧行为）
        if not self.output_dir:
            self.output_dir = os.path.dirname(self.audio_files[0])
            self.lbl_dir.config(text=self.output_dir, fg="#4AF626")
            self.log(texts.LOG_OUTPUT_FALLBACK.format(dir=self.output_dir))

        plan = self._build_plan()
        if plan.need_stt and not module_available("faster_whisper"):
            messagebox.showerror(
                texts.DLG_MISSING_ASR_TITLE,
                texts.DLG_MISSING_ASR_MSG.format(exe=sys.executable),
            )
            return

        self._stop = False
        self._proc = None
        self.progress_var.set(0)
        self.lock_ui(True)

        tasks = []
        if plan.only_denoise:
            tasks.append(texts.ACT_ONLY_DENOISE)
        if plan.need_stt:
            formats = " / ".join(
                [name for name, on in (("SRT", plan.srt), ("TXT", plan.txt)) if on])
            tasks.append(texts.TASK_SUBTITLE.format(formats=formats))
        if plan.mux_original:
            tasks.append(texts.TASK_MUX_ORIGINAL)
        if plan.mux_denoised:
            tasks.append(texts.TASK_MUX_DENOISED)

        self.log(texts.LOG_TASK_HEADER)
        self.log(texts.LOG_OUTPUT_DIR.format(dir=plan.output_dir))
        self.log(texts.LOG_DENOISE_MODEL_LINE.format(
            denoise=denoise_desc(plan.denoise_mode),
            model=plan.model_name or texts.TXT_MODEL_OFF))
        self.log(texts.LOG_TASKS.format(tasks=" + ".join(tasks)))
        if plan.need_stt and not whisper_model_ready(plan.model_name):
            self.log(texts.LOG_FIRST_MODEL.format(model=plan.model_name))
        self.log(texts.LOG_START.format(count=len(plan.audio_files)))

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
        self.set_stage(texts.STAGE_CANCELLING)
        self.log(texts.LOG_CANCEL_REQUEST, is_error=True)
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
        self.stage_var.set(texts.STAGE_CANCELLED if self._stop else texts.STAGE_DONE)

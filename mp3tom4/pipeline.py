# -*- coding: utf-8 -*-
"""任务计划（JobPlan）与执行编排。

本模块**不含任何 UI 代码**，也不导入任何 ui 模块：与界面/线程的交互全部通过
构造参数传入的回调完成（log / set_progress / set_stage / should_stop / on_proc /
on_done）。依赖方向：config、ffmpeg、denoise、asr、subtitle → pipeline。
"""

import os
import shutil
import tempfile
import time
import traceback
from dataclasses import dataclass

from .asr import transcribe_audio
from .config import (
    DEFAULT_DENOISE,
    DEFAULT_MODE,
    DEFAULT_STT_LANG,
    DEFAULT_STT_MODEL,
    DENOISE_MODES,
    SIZE_MODES,
    STT_LANGS,
    STT_MODELS,
    STT_OFF,
    remove_file_quiet,
)
from .denoise import prepare_asr_audio, render_denoised_audio
from .ffmpeg import convert_one, probe_duration, unique_path
from .subtitle import write_srt, write_txt

# ==================== 阶段 / 步骤名称 ====================
STEP_DENOISE = "降噪"
STEP_STT = "语音识别"
STEP_MUX_ORIGINAL = "封装原声视频"
STEP_MUX_DENOISE = "封装降噪视频"
STAGE_FILE_STEP = "第 {index}/{total} 个 · {name} · 正在{step}（{step_index}/{step_total}）"

TXT_DENOISE_OFF = "关闭"
TXT_LANG_AUTO = "自动检测"
TXT_NO_FORMAT = "（未勾选格式）"

# ==================== 日志模板（与拆分前逐字一致）====================
LOG_FILE_START = "[{index}/{total}] {name}\n"
LOG_DURATION_UNKNOWN = "  ⚠ 无法读取时长，进度条将不准确（不影响输出）。\n"
LOG_DENOISE_START = "  🧹 降噪中（{desc}）...\n"
LOG_DENOISE_FAILED = "  ❌ 降噪失败，跳过该文件。\n"
LOG_DENOISE_DONE = "  ✅ 降噪音频：{name}\n"
LOG_DENOISE_MISSING = "  ⚠ 缺少降噪音频，跳过降噪视频。\n"
LOG_ASR_START = "  🎧 识别中（{model} · {lang}）...\n"
LOG_ASR_PREPARE_FAILED = "  ⚠ 音频预处理失败，跳过字幕生成。\n"
LOG_ASR_EMPTY = "  ⚠ 未识别到有效语音，未生成字幕。\n"
LOG_ASR_DONE = (
    "  ✅ 字幕已生成：{count} 条 · 语种 {lang} ({prob:.0%}) · 耗时 {elapsed:.0f}s\n"
    "     → {files}\n"
)
LOG_ASR_FAILED = "  ❌ 语音识别失败：{exc}\n"
LOG_MUX_START = "  🎬 封装视频：{name}\n"
LOG_MUX_CANCELLED = "  🛑 已取消，删除未完成的输出文件。\n"
LOG_MUX_DONE = "  ✅ 成功：{name}（{size:.2f} MB）\n"
LOG_MUX_FAILED = "  ❌ 视频封装失败：{detail}\n"
LOG_FILE_CANCELLED = "  🛑 已取消当前文件，跳过剩余任务。\n"
LOG_CRASH = ">>> ❌ 任务异常终止：\n{summary}\n"
LOG_SEPARATOR = "\n" + "=" * 64 + "\n"
LOG_CANCELLED_TOTAL = ">>> 🛑 任务已取消：已完成 {completed}/{total} 个文件。\n"
LOG_ALL_DONE = ">>> 🎉 批量任务完成：成功 {success} 个，失败 {failed} 个。\n"
LOG_OUTPUT_DIR = ">>> 📂 输出目录：{dir}\n"
LOG_NEXT_STEP = ">>> 💡 下一步：打开 YouTube Studio 批量上传即可。\n"


@dataclass
class JobPlan:
    """主线程读取完所有 Tk 变量后打包出的纯数据任务计划。

    工作线程只读这份快照，绝不再触碰任何 *_var，避免跨线程访问 Tk 对象。
    """
    audio_files: list
    output_dir: str
    image_path: str
    size_mode: str
    model_name: str | None
    language: str | None
    denoise_mode: str | None
    srt: bool
    txt: bool
    mux_original: bool
    mux_denoised: bool
    need_stt: bool
    need_denoise: bool
    only_denoise: bool
    # ffmpeg 路径同样是主线程读到的快照（拆分前由 UI 的 self.ffmpeg_path 提供）
    ffmpeg_path: str = ""


def denoise_desc(mode):
    if not mode:
        return TXT_DENOISE_OFF
    return {v: k for k, v in DENOISE_MODES.items()}.get(mode, mode)


def option_flags(model_code, denoise_code, srt, txt, mux_original, mux_denoised):
    """把界面选项折算成「本次要做什么」的布尔组合（纯函数，不触碰工作线程）。"""
    denoise_on = denoise_code != "off"
    srt = bool(srt)
    txt = bool(txt)
    mux_original = bool(mux_original)
    mux_denoised = bool(mux_denoised) and denoise_on
    need_stt = (model_code != STT_OFF) and (srt or txt)
    only_denoise = denoise_on and not need_stt and not mux_original and not mux_denoised
    return {
        "stt_on": model_code != STT_OFF,
        "denoise_on": denoise_on,
        "need_stt": need_stt,
        "mux_original": mux_original,
        "mux_denoised": mux_denoised,
        "only_denoise": only_denoise,
    }


def build_plan(*, audio_files, output_dir, image_path, size_label, model_code, denoise_code,
               lang_code, srt, txt, mux_original, mux_denoised, ffmpeg_path=""):
    """由纯值（非 Tk 变量）构造 JobPlan，供 UI 在主线程调用。"""
    model_name = None if model_code == STT_OFF else model_code
    denoise_mode = None if denoise_code == "off" else denoise_code
    language = None if lang_code == "auto" else lang_code

    srt = bool(srt)
    txt = bool(txt)
    mux_original = bool(mux_original)
    mux_denoised = bool(mux_denoised) and denoise_mode is not None

    need_stt = (model_name is not None) and (srt or txt)
    only_denoise = (denoise_mode is not None) and not need_stt \
        and not mux_original and not mux_denoised
    need_denoise = (denoise_mode is not None) and (
        need_stt or mux_denoised or only_denoise)

    return JobPlan(
        audio_files=list(audio_files),
        output_dir=output_dir,
        image_path=image_path,
        size_mode=SIZE_MODES.get(size_label, DEFAULT_MODE),
        model_name=model_name,
        language=language,
        denoise_mode=denoise_mode,
        srt=srt,
        txt=txt,
        mux_original=mux_original,
        mux_denoised=mux_denoised,
        need_stt=need_stt,
        need_denoise=need_denoise,
        only_denoise=only_denoise,
        ffmpeg_path=ffmpeg_path,
    )


def build_steps(plan):
    """按实际需要的步骤动态分配 0-100 的进度区间。"""
    raw = []
    if plan.need_denoise:
        raw.append((STEP_DENOISE, 30))
    if plan.need_stt:
        raw.append((STEP_STT, 40))
    if plan.mux_original:
        raw.append((STEP_MUX_ORIGINAL, 30))
    if plan.mux_denoised:
        raw.append((STEP_MUX_DENOISE, 30))
    total_weight = sum(weight for _, weight in raw) or 1
    steps, cursor = [], 0.0
    for name, weight in raw:
        span = weight * 100.0 / total_weight
        steps.append((name, cursor, cursor + span))
        cursor += span
    return steps


class Pipeline:
    """按 JobPlan 执行单文件 / 批量任务，全部对外交互走回调。"""

    def __init__(self, plan, log=None, set_progress=None, set_stage=None,
                 should_stop=None, on_proc=None, on_done=None):
        self.plan = plan
        self._log_cb = log
        self._progress_cb = set_progress
        self._stage_cb = set_stage
        self._stop_cb = should_stop
        self._proc_cb = on_proc
        self._done_cb = on_done

    # ---------- 回调包装 ----------
    def log(self, text, is_error=False):
        if self._log_cb:
            self._log_cb(text, is_error)

    def set_progress(self, value):
        if self._progress_cb:
            self._progress_cb(value)

    def set_stage(self, text):
        if self._stage_cb:
            self._stage_cb(text)

    def should_stop(self) -> bool:
        return bool(self._stop_cb()) if self._stop_cb else False

    def _set_proc(self, proc):
        if self._proc_cb:
            self._proc_cb(proc)

    # ---------- 单文件步骤 ----------
    def _do_stt(self, asr_src, stem, duration, p_start, p_end):
        """语音识别并按勾选写出 SRT / TXT；失败不影响后续步骤。"""
        plan = self.plan
        workdir = tempfile.mkdtemp(prefix="mp3tomp4_asr_")
        started = time.time()
        try:
            lang_text = plan.language or TXT_LANG_AUTO
            self.log(LOG_ASR_START.format(model=plan.model_name, lang=lang_text))
            # 降噪音频是 48k 成片音轨，这里统一重新解码成 ASR 需要的 16k 单声道
            asr_input = prepare_asr_audio(
                plan.ffmpeg_path, asr_src, "off", workdir, self.log)
            if not asr_input:
                self.log(LOG_ASR_PREPARE_FAILED, True)
                return False
            if self.should_stop():
                return False

            segments, info = transcribe_audio(
                asr_input, plan.model_name, plan.language, duration,
                on_progress=lambda p: self.set_progress(
                    p_start + (p_end - p_start) * p / 100.0),
                should_stop=self.should_stop,
                log=self.log,
            )
            if self.should_stop():
                return False
            if not segments:
                self.log(LOG_ASR_EMPTY, True)
                return False

            produced = []
            if plan.srt:
                srt_path = unique_path(os.path.join(plan.output_dir, f"{stem}.srt"))
                write_srt(segments, srt_path)
                produced.append(os.path.basename(srt_path))
            if plan.txt:
                txt_path = unique_path(os.path.join(plan.output_dir, f"{stem}.txt"))
                write_txt(segments, txt_path)
                produced.append(os.path.basename(txt_path))

            lang_name = getattr(info, "language", "?")
            try:
                prob = float(getattr(info, "language_probability", 0.0) or 0.0)
            except Exception:
                prob = 0.0
            self.log(LOG_ASR_DONE.format(
                count=len(segments),
                lang=lang_name,
                prob=prob,
                elapsed=time.time() - started,
                files=" / ".join(produced) if produced else TXT_NO_FORMAT,
            ))
            return True
        except Exception as exc:
            self.log(LOG_ASR_FAILED.format(exc=exc), True)
            return False
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _mux_one(self, audio_src, out_path, duration, p_start, p_end):
        """封面 + 音频封装 MP4；取消或失败时删除半成品。"""
        plan = self.plan
        self.log(LOG_MUX_START.format(name=os.path.basename(out_path)))
        rc, err = convert_one(
            plan.ffmpeg_path, audio_src, plan.image_path, out_path, plan.size_mode, duration,
            on_progress=lambda p: self.set_progress(
                p_start + (p_end - p_start) * p / 100.0),
            should_stop=self.should_stop,
            on_proc=self._set_proc,
        )
        if self.should_stop():
            remove_file_quiet(out_path)
            self.log(LOG_MUX_CANCELLED, True)
            return False
        if rc == 0 and os.path.exists(out_path):
            size_mb = os.path.getsize(out_path) / 1048576.0
            self.log(LOG_MUX_DONE.format(name=os.path.basename(out_path), size=size_mb))
            return True
        detail = (err or "未知错误").splitlines()
        detail_text = " | ".join(detail[-3:]) if detail else "未知错误"
        self.log(LOG_MUX_FAILED.format(detail=detail_text[:400]), True)
        remove_file_quiet(out_path)
        return False

    # ---------- 批量执行 ----------
    def run(self):
        plan = self.plan
        total = len(plan.audio_files)
        steps = build_steps(plan)
        success = failed = completed = 0
        try:
            for index, audio_path in enumerate(plan.audio_files, start=1):
                if self.should_stop():
                    break
                base_name = os.path.basename(audio_path)
                stem = os.path.splitext(base_name)[0]
                self.set_progress(0)
                self.log(LOG_FILE_START.format(index=index, total=total, name=base_name))

                duration = 0.0
                if plan.need_stt or plan.mux_original or plan.mux_denoised:
                    duration = probe_duration(plan.ffmpeg_path, audio_path)
                    if duration <= 0:
                        self.log(LOG_DURATION_UNKNOWN)

                denoised_audio = ""
                file_failed = False
                cancelled = False

                for step_index, (step_name, p_start, p_end) in enumerate(steps, start=1):
                    if self.should_stop():
                        cancelled = True
                        break
                    self.set_stage(STAGE_FILE_STEP.format(
                        index=index, total=total, name=base_name,
                        step=step_name, step_index=step_index, step_total=len(steps)))

                    if step_name == STEP_DENOISE:
                        out_wav = unique_path(
                            os.path.join(plan.output_dir, f"{stem}_denoised.wav"))
                        self.log(LOG_DENOISE_START.format(
                            desc=denoise_desc(plan.denoise_mode)))
                        ok = render_denoised_audio(
                            plan.ffmpeg_path, audio_path, out_wav, plan.denoise_mode,
                            should_stop=self.should_stop,
                            log=self.log,
                            progress_cb=lambda p, a=p_start, b=p_end: self.set_progress(
                                a + (b - a) * p / 100.0),
                            on_proc=self._set_proc,
                        )
                        if not ok:
                            if self.should_stop():
                                cancelled = True
                            else:
                                self.log(LOG_DENOISE_FAILED, True)
                                file_failed = True
                            break
                        denoised_audio = out_wav
                        self.log(LOG_DENOISE_DONE.format(name=os.path.basename(out_wav)))

                    elif step_name == STEP_STT:
                        if not self._do_stt(denoised_audio or audio_path,
                                            stem, duration, p_start, p_end) and self.should_stop():
                            cancelled = True
                            break

                    else:
                        if step_name == STEP_MUX_DENOISE:
                            src_audio, suffix = denoised_audio, "_denoised"
                        else:
                            src_audio, suffix = audio_path, ""
                        if not src_audio:
                            self.log(LOG_DENOISE_MISSING, True)
                            continue
                        out_path = unique_path(
                            os.path.join(plan.output_dir, f"{stem}{suffix}.mp4"))
                        if not self._mux_one(src_audio, out_path,
                                             duration, p_start, p_end):
                            if self.should_stop():
                                cancelled = True
                                break
                            file_failed = True
                            break

                    self.set_progress(p_end)

                if cancelled:
                    self.log(LOG_FILE_CANCELLED, True)
                    break
                if file_failed:
                    failed += 1
                else:
                    success += 1
                    completed += 1
                self.set_progress(100)
        except Exception:
            summary = "\n".join(traceback.format_exc().strip().splitlines()[-6:])
            self.log(LOG_CRASH.format(summary=summary), True)
        finally:
            self._set_proc(None)
            self.log(LOG_SEPARATOR)
            if self.should_stop():
                self.log(LOG_CANCELLED_TOTAL.format(completed=completed, total=total), True)
            else:
                self.log(LOG_ALL_DONE.format(success=success, failed=failed))
                self.log(LOG_OUTPUT_DIR.format(dir=plan.output_dir))
                self.log(LOG_NEXT_STEP)
            if self._done_cb:
                self._done_cb()

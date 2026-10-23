# -*- coding: utf-8 -*-
"""pipeline 模块：JobPlan 推导（六种组合 + only_denoise）与五条回归链路。"""

import inspect
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from mp3tom4 import pipeline as pipeline_mod
from mp3tom4.ffmpeg import probe_duration
from mp3tom4.pipeline import Pipeline, build_plan, build_steps, option_flags

BASE = dict(
    audio_files=["/tmp/a.mp3"],
    output_dir="/tmp/out",
    image_path="/tmp/cover.png",
    size_mode="720p",
    model_code="tiny",
    denoise_code="off",
    lang_code="auto",
    srt=False,
    txt=False,
    mux_original=False,
    mux_denoised=False,
)


def make_plan(**overrides):
    kwargs = dict(BASE)
    kwargs.update(overrides)
    return build_plan(**kwargs)


# ==================== JobPlan 推导（纯逻辑）====================
def test_plan_srt_only():
    plan = make_plan(srt=True)
    assert plan.need_stt is True
    assert plan.need_denoise is False
    assert plan.only_denoise is False
    assert plan.mux_original is False and plan.mux_denoised is False
    assert plan.model_name == "tiny"
    assert plan.language is None


def test_plan_txt_only():
    plan = make_plan(txt=True)
    assert plan.need_stt is True
    assert plan.need_denoise is False
    assert plan.only_denoise is False
    assert plan.srt is False and plan.txt is True


def test_plan_srt_and_txt():
    plan = make_plan(srt=True, txt=True)
    assert plan.need_stt is True
    assert plan.srt is True and plan.txt is True
    assert plan.need_denoise is False


def test_plan_original_mp4_only():
    plan = make_plan(model_code="off", mux_original=True)
    assert plan.need_stt is False
    assert plan.need_denoise is False
    assert plan.only_denoise is False
    assert plan.mux_original is True
    assert plan.model_name is None


def test_plan_denoised_mp4_only():
    plan = make_plan(model_code="off", denoise_code="arnndn", mux_denoised=True)
    assert plan.need_denoise is True
    assert plan.mux_denoised is True
    assert plan.need_stt is False
    assert plan.only_denoise is False
    assert plan.denoise_mode == "arnndn"


def test_plan_everything():
    plan = make_plan(srt=True, txt=True, denoise_code="arnndn",
                     mux_original=True, mux_denoised=True)
    assert plan.need_stt is True
    assert plan.need_denoise is True
    assert plan.only_denoise is False
    assert plan.mux_original is True and plan.mux_denoised is True


def test_plan_only_denoise_scenario():
    plan = make_plan(model_code="off", denoise_code="arnndn")
    assert plan.only_denoise is True
    assert plan.need_denoise is True
    assert plan.need_stt is False
    assert plan.mux_original is False and plan.mux_denoised is False


def test_plan_denoise_off_ignores_denoised_mux():
    plan = make_plan(model_code="off", denoise_code="off", mux_denoised=True)
    assert plan.mux_denoised is False
    assert plan.need_denoise is False
    assert plan.only_denoise is False


def test_plan_stt_off_with_subtitle_toggles():
    plan = make_plan(model_code="off", srt=True, txt=True)
    assert plan.need_stt is False
    assert plan.need_denoise is False
    assert plan.only_denoise is False


def test_plan_language_mapping():
    assert make_plan(lang_code="auto").language is None
    assert make_plan(lang_code="zh").language == "zh"
    assert make_plan(lang_code="en").language == "en"


def test_plan_size_mode_mapping():
    # 内部值直通
    assert make_plan(size_mode="1080p").size_mode == "1080p"
    assert make_plan(size_mode="orig").size_mode == "orig"
    # 旧版显示文案仍可识别（向后兼容）
    assert make_plan(size_mode="720p (1280x720)").size_mode == "720p"
    assert make_plan(size_mode="原图尺寸（仅偶数修正）").size_mode == "orig"
    # 无法识别时回退默认值
    assert make_plan(size_mode="不存在的模式").size_mode == "1080p"


def test_plan_keeps_ffmpeg_path():
    assert make_plan(ffmpeg_path="/x/ffmpeg.exe").ffmpeg_path == "/x/ffmpeg.exe"


def test_do_stt_uses_denoise_mode_from_plan(monkeypatch):
    """识别前的降噪模式必须来自任务计划，而不是硬编码的 "off"。"""
    captured = {}

    def fake_prepare(ffmpeg, src, mode, workdir, log=None):
        captured["mode"] = mode
        return ""  # 空串让 _do_stt 立即走「预处理失败」分支，避免真正转写

    monkeypatch.setattr(pipeline_mod, "prepare_asr_audio", fake_prepare)
    plan = make_plan(srt=True, denoise_code="gtcrn")
    pipeline = Pipeline(plan)

    assert pipeline._do_stt("/tmp/a.mp3", "stem", 0.0, 0.0, 100.0,
                            denoise_mode=plan.denoise_mode,
                            already_denoised=False) is False
    assert captured["mode"] == "gtcrn"

    # 源音频已经是降噪产物时不得重复降噪
    captured.clear()
    pipeline._do_stt("/tmp/a_denoised.wav", "stem", 0.0, 0.0, 100.0,
                     denoise_mode=plan.denoise_mode,
                     already_denoised=True)
    assert captured["mode"] == "off"

    # 计划本身关闭降噪时同样透传 "off"
    captured.clear()
    off_plan = make_plan(srt=True, denoise_code="off")
    Pipeline(off_plan)._do_stt("/tmp/a.mp3", "stem", 0.0, 0.0, 100.0,
                               denoise_mode=off_plan.denoise_mode,
                               already_denoised=False)
    assert captured["mode"] == "off"


@pytest.mark.parametrize("overrides", [
    {"srt": True},
    {"txt": True},
    {"srt": True, "txt": True},
    {"model_code": "off", "mux_original": True},
    {"model_code": "off", "denoise_code": "arnndn", "mux_denoised": True},
    {"srt": True, "txt": True, "denoise_code": "arnndn",
     "mux_original": True, "mux_denoised": True},
    {"model_code": "off", "denoise_code": "arnndn"},
    {"model_code": "off", "denoise_code": "arnndn", "srt": True},
])
def test_option_flags_matches_plan(overrides):
    plan = make_plan(**overrides)
    flags = option_flags(
        overrides.get("model_code", BASE["model_code"]),
        overrides.get("denoise_code", BASE["denoise_code"]),
        overrides.get("srt", False),
        overrides.get("txt", False),
        overrides.get("mux_original", False),
        overrides.get("mux_denoised", False),
    )
    assert flags["need_stt"] == plan.need_stt
    assert flags["denoise_on"] == (plan.denoise_mode is not None)
    assert flags["mux_original"] == plan.mux_original
    assert flags["mux_denoised"] == plan.mux_denoised
    assert flags["only_denoise"] == plan.only_denoise


def test_build_steps_dynamic_weights():
    plan = make_plan(srt=True, denoise_code="arnndn",
                     mux_original=True, mux_denoised=True)
    steps = build_steps(plan)
    assert [name for name, _a, _b in steps] == [
        pipeline_mod.STEP_DENOISE,
        pipeline_mod.STEP_STT,
        pipeline_mod.STEP_MUX_ORIGINAL,
        pipeline_mod.STEP_MUX_DENOISE,
    ]
    assert steps[0][1] == 0.0
    assert steps[-1][2] == pytest.approx(100.0)
    for current, following in zip(steps, steps[1:]):
        assert current[2] == pytest.approx(following[1])


def test_build_steps_empty_plan():
    assert build_steps(make_plan(model_code="off", denoise_code="off")) == []


def test_pipeline_has_no_ui_dependency():
    """依赖方向守卫：pipeline 不得 import 任何 ui 模块。"""
    source = inspect.getsource(pipeline_mod)
    assert "from .ui" not in source
    assert "from ..ui" not in source
    assert "import tkinter" not in source


def test_subtitle_is_pure_module():
    from mp3tom4 import subtitle as subtitle_mod

    source = inspect.getsource(subtitle_mod)
    assert "from .config" not in source
    assert "from .ffmpeg" not in source
    assert "tkinter" not in source


# ==================== 五条回归链路（真实 ffmpeg）====================
class Recorder:
    def __init__(self):
        self.logs = []
        self.progress = []
        self.stages = []
        self.done = 0

    def log(self, text, is_error=False):
        self.logs.append((text, is_error))

    def set_progress(self, value):
        self.progress.append(value)

    def set_stage(self, text):
        self.stages.append(text)

    def on_done(self):
        self.done += 1


def run_pipeline(plan):
    rec = Recorder()
    Pipeline(
        plan,
        log=rec.log,
        set_progress=rec.set_progress,
        set_stage=rec.set_stage,
        should_stop=lambda: False,
        on_proc=lambda proc: None,
        on_done=rec.on_done,
    ).run()
    return rec


def _fake_transcribe(audio_path, model_name, language, duration,
                     on_progress, should_stop, log=None):
    """替身：避免测试加载 Whisper 权重，但保留真实解码/写盘链路。"""
    if on_progress:
        on_progress(50.0)
    segments = [
        {"start": 0.0, "end": 1.0, "text": "hello"},
        {"start": 1.0, "end": 2.0, "text": "world"},
    ]
    return segments, SimpleNamespace(language="en", language_probability=0.98)


def _out_dir(tmp_path):
    path = tmp_path / "out"
    path.mkdir()
    return path


@pytest.mark.integration
def test_flow_1_txt_only(monkeypatch, ffmpeg_path, sine_audio, tmp_path):
    """链路 1：只勾 TXT → need_stt=True，只产出 .txt，不产生视频。"""
    monkeypatch.setattr(pipeline_mod, "transcribe_audio", _fake_transcribe)
    out_dir = _out_dir(tmp_path)
    plan = build_plan(
        audio_files=[sine_audio], output_dir=str(out_dir), image_path="",
        size_mode="720p", model_code="tiny", denoise_code="off",
        lang_code="auto", srt=False, txt=True,
        mux_original=False, mux_denoised=False, ffmpeg_path=ffmpeg_path)
    assert plan.need_stt is True

    rec = run_pipeline(plan)

    stem = Path(sine_audio).stem
    txt_path = out_dir / f"{stem}.txt"
    assert txt_path.is_file()
    assert txt_path.read_text(encoding="utf-8") == "hello world\n"
    assert not list(out_dir.glob("*.mp4"))
    assert not list(out_dir.glob("*.srt"))
    assert rec.done == 1

    # 重名再跑一次 → 自动加序号，不覆盖
    run_pipeline(plan)
    assert (out_dir / f"{stem} (1).txt").is_file()
    assert txt_path.read_text(encoding="utf-8") == "hello world\n"


@pytest.mark.integration
def test_flow_2_original_mp4(ffmpeg_path, sine_audio, black_png, tmp_path):
    """链路 2：只勾原声 MP4 → 产出 <stem>.mp4，时长约 3 秒。"""
    out_dir = _out_dir(tmp_path)
    plan = build_plan(
        audio_files=[sine_audio], output_dir=str(out_dir), image_path=black_png,
        size_mode="720p", model_code="off", denoise_code="off",
        lang_code="auto", srt=False, txt=False,
        mux_original=True, mux_denoised=False, ffmpeg_path=ffmpeg_path)
    assert plan.need_denoise is False and plan.need_stt is False

    run_pipeline(plan)

    stem = Path(sine_audio).stem
    mp4 = out_dir / f"{stem}.mp4"
    assert mp4.is_file() and mp4.stat().st_size > 0
    assert 2.5 <= probe_duration(ffmpeg_path, str(mp4)) <= 3.6


@pytest.mark.integration
def test_flow_3_denoise_and_denoised_mp4(ffmpeg_path, sine_audio, black_png,
                                        denoise_model, tmp_path):
    """链路 3：降噪 + 降噪 MP4 → 48kHz/2ch WAV + 降噪配图 MP4。"""
    out_dir = _out_dir(tmp_path)
    plan = build_plan(
        audio_files=[sine_audio], output_dir=str(out_dir), image_path=black_png,
        size_mode="720p", model_code="off", denoise_code="arnndn",
        lang_code="auto", srt=False, txt=False,
        mux_original=False, mux_denoised=True, ffmpeg_path=ffmpeg_path)
    assert plan.need_denoise is True

    run_pipeline(plan)

    stem = Path(sine_audio).stem
    wav_path = out_dir / f"{stem}_denoised.wav"
    assert wav_path.is_file()
    with wave.open(str(wav_path), "rb") as handle:
        assert handle.getframerate() == 48000
        assert handle.getnchannels() == 2
        assert handle.getsampwidth() == 2

    mp4 = out_dir / f"{stem}_denoised.mp4"
    assert mp4.is_file() and mp4.stat().st_size > 0
    assert 2.5 <= probe_duration(ffmpeg_path, str(mp4)) <= 3.6


@pytest.mark.integration
def test_flow_4_both_mp4(ffmpeg_path, sine_audio, black_png, denoise_model, tmp_path):
    """链路 4：两个 MP4 同时勾 → 两个文件都在，互不覆盖。"""
    out_dir = _out_dir(tmp_path)
    plan = build_plan(
        audio_files=[sine_audio], output_dir=str(out_dir), image_path=black_png,
        size_mode="720p", model_code="off", denoise_code="arnndn",
        lang_code="auto", srt=False, txt=False,
        mux_original=True, mux_denoised=True, ffmpeg_path=ffmpeg_path)

    run_pipeline(plan)

    stem = Path(sine_audio).stem
    original = out_dir / f"{stem}.mp4"
    denoised = out_dir / f"{stem}_denoised.mp4"
    assert original.is_file() and denoised.is_file()
    assert original.stat().st_size > 0 and denoised.stat().st_size > 0
    assert original.name != denoised.name


@pytest.mark.integration
def test_flow_5_only_denoise(ffmpeg_path, sine_audio, denoise_model, tmp_path):
    """链路 5：只开降噪 → 只产出 <stem>_denoised.wav。"""
    out_dir = _out_dir(tmp_path)
    plan = build_plan(
        audio_files=[sine_audio], output_dir=str(out_dir), image_path="",
        size_mode="720p", model_code="off", denoise_code="arnndn",
        lang_code="auto", srt=False, txt=False,
        mux_original=False, mux_denoised=False, ffmpeg_path=ffmpeg_path)
    assert plan.only_denoise is True

    run_pipeline(plan)

    stem = Path(sine_audio).stem
    assert sorted(path.name for path in out_dir.iterdir()) == [f"{stem}_denoised.wav"]

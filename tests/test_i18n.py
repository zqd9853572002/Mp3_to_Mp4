# -*- coding: utf-8 -*-
"""i18n 框架：词条一致性、占位符、缺失 key、语言回退、持久化与硬编码中文扫描。"""

import ast
import importlib
import json
import re
from pathlib import Path

import pytest

from mp3tom4 import i18n

PACKAGE_ROOT = Path(i18n.__file__).resolve().parent
LOCALE_DIR = PACKAGE_ROOT / "locale"
LANGUAGES = ("zh_CN", "zh_TW", "en")
CJK = re.compile(r"[\u4e00-\u9fff]")


def _load(code):
    return json.loads((LOCALE_DIR / f"{code}.json").read_text(encoding="utf-8"))


# ==================== 词条一致性 ====================
def test_catalog_key_sets_are_identical():
    """三份词条的 key 集合必须完全相同，缺失/多余都会打印差集。"""
    base = set(_load("zh_CN"))
    assert base, "zh_CN 词条为空"

    for code in ("zh_TW", "en"):
        other = set(_load(code))
        missing = sorted(base - other)
        extra = sorted(other - base)
        assert not missing and not extra, (
            f"{code} 与 zh_CN 的 key 不一致：缺失 {missing}，多余 {extra}")


def test_catalog_values_are_non_empty_strings():
    for code in LANGUAGES:
        table = _load(code)
        assert table, f"{code} 词条为空"
        empty = [key for key, value in table.items()
                 if not isinstance(value, str) or not value.strip()]
        assert not empty, f"{code} 存在空值词条: {empty}"
        # 反向：词条文件里不得残留 key 自指（通常是漏翻）
        same_as_key = [key for key, value in table.items() if key == value]
        assert not same_as_key, f"{code} 存在未翻译词条: {same_as_key}"


def test_catalog_count_matches_documented_total():
    """交付说明里报告的就是这个数字（三语条数一致）。"""
    counts = {code: len(_load(code)) for code in LANGUAGES}
    assert len(set(counts.values())) == 1, f"三语条数不一致: {counts}"


def test_available_reports_three_languages():
    assert sorted(i18n.available()) == sorted(LANGUAGES)


def test_supported_languages_use_self_names():
    assert i18n.SUPPORTED_LANGUAGES == [
        ("zh_CN", "简体中文"), ("zh_TW", "繁體中文"), ("en", "English")]
    assert i18n.language_label("zh_TW") == "繁體中文"
    assert i18n.language_label("en") == "English"


# ==================== t() 行为 ====================
def test_t_placeholder_substitution():
    i18n.set_language("zh_CN", persist=False)
    assert i18n.t("stage.ready_hint", count=3, actions="TXT") == "就绪 · 3 个音频 · TXT"
    i18n.set_language("en", persist=False)
    assert i18n.t("stage.ready_hint", count=3, actions="TXT") == (
        "Ready · 3 file(s) · TXT")


def test_t_keeps_numeric_format_specs():
    """`{prob:.0%}` / `{size:.2f}` 这类格式说明必须仍然生效。"""
    text = i18n.t("log.asr_done", count=2, lang="en", prob=0.98,
                  elapsed=1.4, files="a.srt")
    assert "98%" in text
    assert "1s" in text
    text = i18n.t("log.mux_done", name="a.mp4", size=1.2345)
    assert "1.23 MB" in text


def test_t_missing_key_returns_key_without_raising():
    assert i18n.t("no.such.key.exists") == "no.such.key.exists"
    assert i18n.t("no.such.key.exists", value=1) == "no.such.key.exists"


def test_t_unknown_placeholder_does_not_raise():
    # 参数不足时回退为未格式化的模板，而不是抛异常
    assert i18n.t("stage.ready_hint") == "就绪 · {count} 个音频 · {actions}"


def test_set_language_unknown_falls_back_to_default():
    assert i18n.set_language("xx", persist=False) == "zh_CN"
    assert i18n.get_language() == "zh_CN"
    # 空值同样回退
    assert i18n.set_language("", persist=False) == "zh_CN"


def test_set_language_normalizes_locale_variants():
    assert i18n.set_language("zh-Hant", persist=False) == "zh_TW"
    assert i18n.set_language("zh-HK", persist=False) == "zh_TW"
    assert i18n.set_language("zh-CN", persist=False) == "zh_CN"
    assert i18n.set_language("en-US", persist=False) == "en"


# ==================== 持久化 ====================
def test_language_choice_is_persisted_and_reloaded(monkeypatch, tmp_path):
    """切换后配置里写 ui_language；模拟重启（重新 import）仍是该语言。"""
    from mp3tom4 import config

    monkeypatch.setenv("APPDATA", str(tmp_path))
    i18n.set_language("en")
    assert config.load_config()["ui_language"] == "en"

    reloaded = importlib.reload(i18n)
    try:
        assert reloaded.get_language() == "en"
        assert reloaded.t("btn.cancel") == "Cancel"
    finally:
        i18n.set_language("zh_CN", persist=False)
        # 保证后续用例拿到完整词条表
        importlib.reload(i18n)
        i18n.set_language("zh_CN", persist=False)


def test_language_persist_does_not_clobber_other_settings(monkeypatch, tmp_path):
    from mp3tom4 import config

    monkeypatch.setenv("APPDATA", str(tmp_path))
    config.save_config({"size_mode": "720p", "mux_original": True})

    i18n.set_language("zh_TW")
    data = config.load_config()
    assert data["ui_language"] == "zh_TW"
    assert data["size_mode"] == "720p"
    assert data["mux_original"] is True


# ==================== 硬编码中文扫描 ====================
def _docstring_constant_ids(tree):
    """模块/类/函数 docstring 对应的 ast.Constant 节点 id（豁免）。"""
    exempt = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            exempt.add(id(first.value))
    return exempt


def test_no_hardcoded_chinese_in_package():
    """`mp3tom4/` 下除 docstring 外不得出现中文字符串字面量。

    这条用例是「没有只翻一半」的唯一可靠保证：新增遗漏文案会立刻失败。
    """
    offenders = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        exempt = _docstring_constant_ids(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in exempt:
                continue
            if CJK.search(node.value):
                rel = path.relative_to(PACKAGE_ROOT).as_posix()
                offenders.append(f"{rel}:{node.lineno}: {node.value[:48]!r}")

    assert not offenders, (
        "发现硬编码中文字符串（应移入 mp3tom4/locale/*.json）：\n"
        + "\n".join(offenders))


def test_scan_has_no_false_negative_on_locale_only():
    """反向自检：locale JSON 才是中文文案的唯一归属。"""
    json_paths = sorted(LOCALE_DIR.glob("*.json"))
    assert {p.stem for p in json_paths} >= set(LANGUAGES)
    for path in json_paths:
        assert CJK.search(path.read_text(encoding="utf-8")), f"{path.name} 不含中文"


@pytest.mark.parametrize("code", LANGUAGES)
def test_every_key_resolves_in_every_language(code):
    i18n.set_language(code, persist=False)
    table = _load(code)
    missing = [key for key in table if i18n.t(key) == key and key not in table.values()]
    assert not missing, f"{code} 有 {len(missing)} 个 key 无法解析: {missing[:5]}"

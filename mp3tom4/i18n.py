# -*- coding: utf-8 -*-
"""Lightweight runtime translation layer (standard library only).

Design notes
------------
* Every catalog lives next to this module under ``locale/<code>.json`` and is
  read once at import time; switching languages only swaps a pointer, it never
  touches the filesystem again.
* The active language is resolved on first use (not at import) so that
  ``mp3tom4.config`` may import this module at module scope without a circular
  import: reading the saved preference needs ``config.load_config`` which only
  exists once ``config`` finished executing.
* ``t()`` never raises.  A missing key yields the key itself (plus a debug log
  line), so a forgotten entry degrades to a visible key instead of a crash.
"""

import json
import logging
from pathlib import Path

DEFAULT_LANGUAGE = "zh_CN"

# Order matters: it is the order used by the language selector.
_LANGUAGE_CODES = ("zh_CN", "zh_TW", "en")
_LOCALE_DIR = Path(__file__).resolve().parent / "locale"

_CATALOG = {}
_current_language = None


def _load_catalogs():
    for code in _LANGUAGE_CODES:
        path = _LOCALE_DIR / f"{code}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logging.debug("i18n: cannot load locale %s", code)
            data = {}
        _CATALOG[code] = data if isinstance(data, dict) else {}


_load_catalogs()

# Public list of (code, self-name).  Self-names come from the catalogs so this
# module itself stays free of translated literals.
SUPPORTED_LANGUAGES = [
    (code, _CATALOG.get(code, {}).get(f"lang.{code}", code))
    for code in _LANGUAGE_CODES
]


def _normalize(code):
    """Map a config / system value to one of the supported codes (or None)."""
    if not code or not isinstance(code, str):
        return None
    raw = code.strip().replace("-", "_")
    if raw in _CATALOG:
        return raw
    low = raw.lower()
    if low.startswith("zh"):
        if any(tag in low for tag in ("tw", "hk", "mo", "hant")):
            return "zh_TW"
        return "zh_CN"
    if low.startswith("en"):
        return "en"
    return None


def _detect_language():
    """Saved preference -> default.

    The first launch always starts in Simplified Chinese instead of following
    the operating-system locale: on machines whose system language is English
    the previous behaviour opened an English window for users who only ever
    used the Chinese UI.  Once the user picks a language explicitly the choice
    is persisted as ``ui_language`` and wins on every later start.
    """
    configured = None
    try:  # deferred import: config imports this module at module scope
        from .config import load_config

        configured = load_config().get("ui_language")
    except Exception:
        configured = None
    return _normalize(configured) or DEFAULT_LANGUAGE


def _ensure_language():
    global _current_language
    if _current_language is None:
        _current_language = _detect_language()
    return _current_language


def _lookup(code, key):
    table = _CATALOG.get(code) or {}
    value = table.get(key)
    return value if isinstance(value, str) else None


def available():
    """Codes whose catalog was loaded successfully."""
    return [code for code in _LANGUAGE_CODES if _CATALOG.get(code)]


def get_language():
    return _ensure_language()


def set_language(code, persist=True):
    """Switch the active language; unknown values fall back to the default.

    ``persist`` writes ``ui_language`` into the user config so the choice
    survives a restart.  Tests / startup detection pass ``persist=False``.
    """
    global _current_language
    target = _normalize(code) or DEFAULT_LANGUAGE
    _current_language = target
    if persist:
        _save_preference(target)
    return target


def _save_preference(code):
    try:
        from .config import load_config, save_config

        cfg = load_config()
        cfg["ui_language"] = code
        save_config(cfg)
    except Exception:
        logging.debug("i18n: cannot persist language %s", code)


def language_label(code):
    """Self-name shown in the language selector (never translated)."""
    normalized = _normalize(code) or code
    return _lookup(normalized, f"lang.{normalized}") or code


def text_for(code, key):
    """Entry in a specific language (used for legacy-value matching)."""
    return _lookup(_normalize(code) or DEFAULT_LANGUAGE, key)


def t(key, **kwargs):
    """Translate ``key`` with optional ``str.format`` placeholders."""
    text = _lookup(_ensure_language(), key)
    if text is None:
        text = _lookup(DEFAULT_LANGUAGE, key)
    if text is None:
        if __debug__:
            logging.debug("i18n: missing key %r for %s", key, _current_language)
        return key
    if not kwargs:
        return text
    try:  # keep numeric values intact for specs such as {prob:.0%}
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError, TypeError):
        try:
            return text.format(**{name: str(value) for name, value in kwargs.items()})
        except Exception:
            if __debug__:
                logging.debug("i18n: bad placeholders for %r", key)
            return text

# -*- coding: utf-8 -*-
"""字幕/文本产物生成：时间戳格式化、按显示宽度折行、SRT/TXT 写入。

**纯函数模块**：只依赖标准库，不得依赖 config / ffmpeg / UI。
"""

import re
import unicodedata
from pathlib import Path


def format_timestamp(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    hours, rem = divmod(total_ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def char_width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(text: str) -> int:
    return sum(char_width(ch) for ch in text)


def wrap_subtitle(text: str, limit: int = 42, max_lines: int = 3):
    """按显示宽度折行：中文占 2 宽度，英文占 1，优先在空格处断开。"""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    if display_width(text) <= limit:
        return [text]
    lines, current, width = [], [], 0
    for ch in text:
        w = char_width(ch)
        if width + w > limit and current:
            line = "".join(current)
            if " " in line:
                head, tail = line.rsplit(" ", 1)
                if head.strip() and tail:
                    lines.append(head.strip())
                    current = list(tail)
                    width = display_width(tail)
                    if ch != " ":
                        current.append(ch)
                        width += w
                    continue
            lines.append(line.strip())
            current = [] if ch == " " else [ch]
            width = 0 if ch == " " else w
        else:
            current.append(ch)
            width += w
    if current:
        lines.append("".join(current).strip())
    return [ln for ln in lines if ln][:max_lines]


def write_srt(segments, path: str) -> None:
    blocks = []
    for index, seg in enumerate(segments, start=1):
        start = max(0.0, seg["start"])
        end = max(start + 0.2, seg["end"])
        lines = wrap_subtitle(seg["text"])
        if not lines:
            continue
        blocks.append(str(index))
        blocks.append(f"{format_timestamp(start)} --> {format_timestamp(end)}")
        blocks.extend(lines)
        blocks.append("")
    Path(path).write_text("\n".join(blocks) + "\n", encoding="utf-8")


def _is_cjk(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def write_txt(segments, path: str) -> None:
    parts = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if parts and not (_is_cjk(parts[-1][-1]) or _is_cjk(text[0])):
            parts.append(" ")
        parts.append(text)
    Path(path).write_text("".join(parts) + "\n", encoding="utf-8")

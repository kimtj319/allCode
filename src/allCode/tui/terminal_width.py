"""Terminal display width helpers."""

from __future__ import annotations

import unicodedata


def char_width(char: str) -> int:
    if not char:
        return 0
    if unicodedata.combining(char):
        return 0
    category = unicodedata.category(char)
    if category in {"Cc", "Cf"}:
        return 0
    if unicodedata.east_asian_width(char) in {"F", "W"}:
        return 2
    return 1


def display_width(text: str) -> int:
    return sum(char_width(char) for char in text)


def clip_display_width(text: str, width: int) -> str:
    used = 0
    out: list[str] = []
    for char in text:
        next_width = char_width(char)
        if used + next_width > width:
            break
        out.append(char)
        used += next_width
    return "".join(out)


def wrap_display_width(text: str, width: int) -> list[str]:
    if width <= 0:
        return [""]
    if not text:
        return [""]
    lines: list[str] = []
    current: list[str] = []
    used = 0
    for char in text:
        char_cols = char_width(char)
        if current and used + char_cols > width:
            lines.append("".join(current))
            current = [char]
            used = char_cols
        else:
            current.append(char)
            used += char_cols
    lines.append("".join(current))
    return lines

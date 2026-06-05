"""Small helpers for committed IME text in the terminal composer."""

from __future__ import annotations

from allCode.tui.terminal_width import display_width


def committed_text_width(text: str) -> int:
    """Return display columns for committed text, including Hangul wide chars."""

    return display_width(text)


def is_committed_text_complete(text: str) -> bool:
    """Text streams give allCode committed Unicode text, not composition events."""

    return bool(text)

"""Sanitize bracketed-paste markers at terminal input boundaries."""

from __future__ import annotations

import re

_RAW_BEGIN = "\x1b[200~"
_RAW_END = "\x1b[201~"
_CARET_BEGIN = "^[[200~"
_CARET_END = "^[[201~"
_PLAIN_BEGIN = "[200~"
_PLAIN_END = "[201~"

_BEGIN_RE = re.compile(r"(?m)^(?:\x1b\[200~|\^\[\[200~|\[200~)")
_END_RE = re.compile(r"(?m)(?:\x1b\[201~|\^\[\[201~|\[201~)$")


def normalize_pasted_text(text: str) -> str:
    """Normalize paste text before it enters the editor buffer."""

    cleaned = strip_bracketed_paste_markers(text)
    return cleaned.replace("\r\n", "\n").replace("\r", "\n")


def strip_bracketed_paste_markers(text: str) -> str:
    """Remove bracketed-paste delimiters only at prompt/paste boundaries.

    The sanitizer intentionally avoids replacing marker-like text in the middle
    of a line so code snippets mentioning the protocol remain intact.
    """

    if not text:
        return text
    cleaned = text
    for begin, end in (
        (_RAW_BEGIN, _RAW_END),
        (_CARET_BEGIN, _CARET_END),
        (_PLAIN_BEGIN, _PLAIN_END),
    ):
        if cleaned.startswith(begin) and cleaned.endswith(end):
            cleaned = cleaned[len(begin) : -len(end)]
            break
    cleaned = _BEGIN_RE.sub("", cleaned)
    cleaned = _END_RE.sub("", cleaned)
    return cleaned

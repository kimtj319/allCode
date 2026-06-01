"""Normalize model Markdown before terminal rendering."""

from __future__ import annotations

import re

from allCode.tui.table_detect import has_markdown_table

_FENCE_RE = re.compile(r"```([a-zA-Z0-9_-]*)\n(.*?)\n```", re.DOTALL)


def normalize_agent_markdown(source: str) -> str:
    """Apply conservative model-output fixes without becoming a full parser."""

    text = unwrap_markdown_table_fences(source)
    return close_unclosed_fence(text)


def unwrap_markdown_table_fences(source: str) -> str:
    """Unwrap ```md fences when they only hide a Markdown table."""

    def replace(match: re.Match[str]) -> str:
        language = match.group(1).strip().lower()
        body = match.group(2)
        if language in {"md", "markdown"} and has_markdown_table(body):
            return body.strip("\n")
        return match.group(0)

    return _FENCE_RE.sub(replace, source)


def close_unclosed_fence(source: str) -> str:
    if source.count("```") % 2 == 1:
        return source.rstrip() + "\n```"
    return source

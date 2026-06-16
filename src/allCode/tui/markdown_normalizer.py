"""Normalize model Markdown before terminal rendering."""

from __future__ import annotations

import re

from allCode.tui.table_detect import has_markdown_table

_FENCE_RE = re.compile(r"```([a-zA-Z0-9_-]*)\n(.*?)\n```", re.DOTALL)
_CITATION_ARTIFACT_RE = re.compile(r"【(\d+)†[^】]+】")
_TITLE_CITATION_RE = re.compile(r"【([^】\n]{1,120})】")
# Harmony/channel control scaffolding emitted as literal text by some servers
# (e.g. "<|channel|>analysis", "<|message|>", and mangled "<|channel>"/"<channel|>").
# It must never appear in the rendered answer. Matches the marker plus an
# immediately-adjacent channel name so the scaffolding is removed cleanly.
_CONTROL_TOKEN_RE = re.compile(
    r"<\|?\s*(?:channel|message|start|end|return|constrain|call|refusal|"
    r"assistant|developer|system|user)\s*\|?>"
    r"(?:[ \t]*(?:analysis|thought|commentary|final)\b)?",
    re.IGNORECASE,
)


def normalize_agent_markdown(source: str) -> str:
    """Apply conservative model-output fixes without becoming a full parser."""

    text = strip_control_tokens(source)
    text = rejoin_orphaned_closing_quote(text)
    text = drop_bold_around_quote(text)
    text = unwrap_markdown_table_fences(text)
    text = normalize_citation_artifacts(text)
    return close_unclosed_fence(text)


# Models frequently emit a newline right before a closing quotation mark, e.g.
# `있지?\n"` or `것인가?\n"**라는`. That orphans the quote on its own line (and
# breaks the surrounding **bold** span so the markers leak as raw text). Pull the
# closing quote back onto the sentence it belongs to.
_ORPHAN_QUOTE_RE = re.compile(r'([?!.])[ \t]*\n[ \t]*(["”])')


def rejoin_orphaned_closing_quote(source: str) -> str:
    return _ORPHAN_QUOTE_RE.sub(r"\1\2", source)


# CommonMark will not form emphasis when the "**" delimiters hug a quotation
# mark (e.g. `**"성공"**`), so the markers leak as raw text. The quotes already
# convey the emphasis, so drop the redundant bold markers to keep the output
# clean instead of leaking "**".
_BOLD_QUOTE_RE = re.compile(r'\*\*\s*("[^"\n]{1,100}")\s*\*\*')


def drop_bold_around_quote(source: str) -> str:
    return _BOLD_QUOTE_RE.sub(r"\1", source)


def strip_control_tokens(source: str) -> str:
    """Remove harmony/channel control scaffolding that leaks into answer text."""

    return _CONTROL_TOKEN_RE.sub("", source)


def normalize_citation_artifacts(source: str) -> str:
    """Collapse provider-style citation artifacts into readable numeric refs."""

    text = _CITATION_ARTIFACT_RE.sub(r"[\1]", source)
    return _TITLE_CITATION_RE.sub(r"[\1]", text)


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

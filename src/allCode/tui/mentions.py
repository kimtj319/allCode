"""``@path`` file mentions in the prompt.

Typing ``@src/app.py`` (or ``@dir/``) in a prompt pulls that file's contents
(or a directory listing) into the turn as context — the same affordance Codex
and Claude Code expose. Only paths that actually resolve inside the workspace
are expanded; anything else is left untouched so ``@`` in prose (emails,
decorators) is never mangled.
"""

from __future__ import annotations

import re
from pathlib import Path

# A mention is an @ that starts a token (preceded by start/whitespace/paren) and
# runs until whitespace. Trailing sentence punctuation is trimmed afterwards.
_MENTION_RE = re.compile(r"(?<![^\s(\[])@([^\s@]+)")
_TRAILING_PUNCT = ".,;:!?)]}"
_MAX_FILE_BYTES = 64 * 1024
_MAX_DIR_ENTRIES = 60


def _clean_token(token: str) -> str:
    while token and token[-1] in _TRAILING_PUNCT:
        token = token[:-1]
    return token


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            data = path.read_bytes()[:_MAX_FILE_BYTES]
            return data.decode("utf-8", errors="replace") + "\n... (truncated) ..."
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def _dir_listing(path: Path) -> str:
    try:
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
    except OSError:
        return "(읽을 수 없는 디렉터리)"
    if len(entries) > _MAX_DIR_ENTRIES:
        shown = entries[:_MAX_DIR_ENTRIES]
        shown.append(f"... (+{len(entries) - _MAX_DIR_ENTRIES} more)")
        entries = shown
    return "\n".join(entries)


def expand_mentions(prompt: str, cwd: Path | str) -> tuple[str, list[str]]:
    """Return ``(augmented_prompt, resolved_tokens)``.

    The visible prompt text is preserved verbatim; resolved file/dir contents
    are appended as a context section so the model sees both the reference and
    the data. When nothing resolves, the prompt is returned unchanged.
    """

    root = Path(cwd).expanduser()
    seen: dict[str, Path] = {}
    for match in _MENTION_RE.finditer(prompt):
        token = _clean_token(match.group(1))
        if not token or token in seen:
            continue
        candidate = Path(token).expanduser()
        resolved = candidate if candidate.is_absolute() else (root / candidate)
        if resolved.exists():
            seen[token] = resolved

    if not seen:
        return prompt, []

    blocks: list[str] = []
    for token, path in seen.items():
        if path.is_dir():
            blocks.append(f"### @{token} (디렉터리)\n```\n{_dir_listing(path)}\n```")
            continue
        content = _read_text(path)
        if content is None:
            continue
        blocks.append(f"### @{token}\n```\n{content}\n```")

    if not blocks:
        return prompt, []
    body = "\n\n".join(blocks)
    augmented = f"{prompt}\n\n--- 멘션된 파일/디렉터리 ---\n{body}"
    return augmented, list(seen.keys())

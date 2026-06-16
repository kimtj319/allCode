"""``@path`` (and ``@path::symbol``) file mentions in the prompt.

Typing ``@src/app.py`` (or ``@dir/``) in a prompt pulls that file's contents
(or a directory listing) into the turn as context — the same affordance Codex
and Claude Code expose. ``@src/app.py::parse`` narrows to a single symbol
(function/class): for Python the symbol's source is sliced out with ``ast`` so
only the relevant definition is attached. Only paths that actually resolve
inside the workspace are expanded; anything else is left untouched so ``@`` in
prose (emails, decorators) is never mangled.
"""

from __future__ import annotations

import ast
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


def _split_symbol(token: str) -> tuple[str, str | None]:
    """Split ``path::symbol`` into ``(path, symbol)``; ``(path, None)`` if none."""
    if "::" in token:
        path_part, _, symbol_part = token.partition("::")
        symbol_part = symbol_part.strip()
        return path_part, (symbol_part or None)
    return token, None


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            data = path.read_bytes()[:_MAX_FILE_BYTES]
            return data.decode("utf-8", errors="replace") + "\n... (truncated) ..."
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def extract_python_symbol(source: str, symbol: str) -> str | None:
    """Return the source of a top-level (or dotted ``Class.method``) Python
    function/class definition, or None if not found / not parseable."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    parts = symbol.split(".")

    def _find(body: list[ast.stmt], names: list[str]) -> ast.AST | None:
        head, rest = names[0], names[1:]
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == head:
                if not rest:
                    return node
                if isinstance(node, ast.ClassDef):
                    return _find(node.body, rest)
                return None
        return None

    node = _find(tree.body, parts)
    if node is None:
        return None
    segment = ast.get_source_segment(source, node)
    return segment


def _symbol_block(path: Path, symbol: str) -> str | None:
    content = _read_text(path)
    if content is None:
        return None
    if path.suffix.lower() == ".py":
        snippet = extract_python_symbol(content, symbol)
        if snippet is not None:
            return snippet
    # Fallback: a textual search for a definition line, otherwise the whole file.
    for line in content.splitlines():
        stripped = line.strip()
        if symbol in stripped and any(
            stripped.startswith(kw) for kw in ("def ", "class ", "function ", "async def ", "func ", "fn ", "const ", "export ")
        ):
            return content
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

    The visible prompt text is preserved verbatim; resolved file/dir/symbol
    contents are appended as a context section so the model sees both the
    reference and the data. When nothing resolves, the prompt is unchanged.
    """

    root = Path(cwd).expanduser()
    # token -> (resolved path, symbol or None)
    seen: dict[str, tuple[Path, str | None]] = {}
    for match in _MENTION_RE.finditer(prompt):
        token = _clean_token(match.group(1))
        if not token or token in seen:
            continue
        path_part, symbol = _split_symbol(token)
        if not path_part:
            continue
        candidate = Path(path_part).expanduser()
        resolved = candidate if candidate.is_absolute() else (root / candidate)
        if resolved.exists():
            seen[token] = (resolved, symbol)

    if not seen:
        return prompt, []

    blocks: list[str] = []
    resolved_tokens: list[str] = []
    for token, (path, symbol) in seen.items():
        if path.is_dir():
            blocks.append(f"### @{token} (디렉터리)\n```\n{_dir_listing(path)}\n```")
            resolved_tokens.append(token)
            continue
        if symbol:
            snippet = _symbol_block(path, symbol)
            if snippet is None:
                continue
            blocks.append(f"### @{token} (심볼 `{symbol}`)\n```\n{snippet}\n```")
            resolved_tokens.append(token)
            continue
        content = _read_text(path)
        if content is None:
            continue
        blocks.append(f"### @{token}\n```\n{content}\n```")
        resolved_tokens.append(token)

    if not blocks:
        return prompt, []
    body = "\n\n".join(blocks)
    augmented = f"{prompt}\n\n--- 멘션된 파일/디렉터리 ---\n{body}"
    return augmented, resolved_tokens

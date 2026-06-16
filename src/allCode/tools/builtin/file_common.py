"""Shared helpers for builtin file tools."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from allCode.workspace.path_resolver import safe_resolve_under_root

DEFAULT_READ_MAX_BYTES = 12_000
LARGE_FILE_BYTES = 20_000


def syntax_warning(path: Path, content: str) -> str | None:
    """Parse just-written content and return a human-readable syntax error, if any.

    AST-aware post-edit check: a ``.py`` file is parsed with ``ast.parse`` and a
    ``.json`` file with ``json.loads`` so a broken edit is reported back to the
    model immediately (and before the slower test step) instead of surfacing as
    an opaque import/runtime failure later. Returns None when the content parses
    or the language is not checked.
    """

    suffix = path.suffix.lower()
    if suffix == ".py":
        try:
            ast.parse(content, filename=str(path))
        except SyntaxError as exc:
            location = f"line {exc.lineno}" if exc.lineno else "unknown line"
            return f"Python 구문 오류 ({location}): {exc.msg}"
        return None
    if suffix == ".json" and content.strip():
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            return f"JSON 구문 오류 (line {exc.lineno}, col {exc.colno}): {exc.msg}"
    return None


class PatchApplicationError(ValueError):
    """Structured patch failure with tool-result metadata."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        match_count: int | None = None,
        search_preview: str = "",
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.match_count = match_count
        self.search_preview = search_preview

    def metadata(self, *, file_path: str) -> dict[str, Any]:
        return {
            "file_path": file_path,
            "match_count": self.match_count,
            "search_preview": self.search_preview,
            "recommended_next_tools": ["read_file", "write_file"] if self.error_type == "patch_ambiguous" else ["read_file", "patch_file"],
            "must_not_repeat_same_patch": True,
            "observation": {
                "kind": "patch_failure",
                "target": file_path,
                "summary": str(self),
                "risk": "low",
            },
        }


def resolve_under_root(root: str, file_path: str) -> Path:
    return safe_resolve_under_root(root, file_path)


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    if not path.is_file():
        raise ValueError(f"path is not a file: {path}")
    return path.read_text(encoding="utf-8")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply_exact_patches(content: str, patches: Any) -> str:
    if not isinstance(patches, list) or not patches:
        raise PatchApplicationError("patches must be a non-empty list", error_type="patch_invalid_request")
    updated = content
    for patch in patches:
        if not isinstance(patch, dict):
            raise PatchApplicationError("each patch must be an object", error_type="patch_invalid_request")
        search = str(patch.get("search", ""))
        replace = str(patch.get("replace", ""))
        if not search:
            raise PatchApplicationError("patch search must be a non-empty string", error_type="patch_invalid_request", match_count=0)
        if _low_context_large_replacement(search, replace):
            raise PatchApplicationError(
                "patch search is too small for a large replacement; read the current range and use write_file or a wider exact search block",
                error_type="patch_ambiguous",
                match_count=updated.count(search),
                search_preview=search[:240],
            )
        count = updated.count(search)
        if count == 1:
            updated = updated.replace(search, replace, 1)
            continue
        if count == 0:
            # The model's search block often differs only in leading/trailing
            # whitespace. Fall back to a line-based match (whitespace-flexible)
            # and reapply the file's own indentation to the replacement.
            flexible = _apply_flexible_patch(updated, search, replace)
            if flexible is not None:
                updated = flexible
                continue
        error_type = "patch_not_found" if count == 0 else "patch_ambiguous"
        raise PatchApplicationError(
            f"patch search must match exactly once, matched {count} times",
            error_type=error_type,
            match_count=count,
            search_preview=search[:240],
        )
    return updated


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _apply_flexible_patch(content: str, search: str, replace: str) -> str | None:
    """Whitespace-flexible single-match fallback for apply_exact_patches.

    Matches the search block against file lines ignoring per-line leading/trailing
    whitespace, but only when exactly one contiguous run matches. The replacement
    is re-indented by the difference between the file's matched indentation and
    the search block's indentation so the result stays correctly indented.
    Returns None when there is no unique match (caller then raises).
    """
    file_lines = content.split("\n")
    search_lines = search.split("\n")
    while search_lines and search_lines[-1] == "":
        search_lines = search_lines[:-1]
    if not search_lines:
        return None
    span = len(search_lines)
    norm_search = [line.strip() for line in search_lines]
    matches = [
        index
        for index in range(0, len(file_lines) - span + 1)
        if [line.strip() for line in file_lines[index : index + span]] == norm_search
    ]
    if len(matches) != 1:
        return None
    start = matches[0]
    window = file_lines[start : start + span]
    # Indentation delta from the first line that has content on both sides.
    indent_delta = ""
    for file_line, search_line in zip(window, search_lines):
        if file_line.strip() and search_line.strip():
            file_indent, search_indent = _leading_ws(file_line), _leading_ws(search_line)
            if file_indent.startswith(search_indent):
                indent_delta = file_indent[len(search_indent) :]
            break
    replace_lines = replace.split("\n")
    while replace_lines and replace_lines[-1] == "":
        replace_lines = replace_lines[:-1]
    adjusted = [(indent_delta + line) if line.strip() else line for line in replace_lines]
    new_lines = file_lines[:start] + adjusted + file_lines[start + span :]
    return "\n".join(new_lines)


def _low_context_large_replacement(search: str, replace: str) -> bool:
    search_lines = [line for line in search.splitlines() if line.strip()]
    replace_lines = [line for line in replace.splitlines() if line.strip()]
    if len(search_lines) > 1 or len(replace_lines) < 6:
        return False
    stripped = search_lines[0].strip()
    if stripped.startswith(("class ", "def ", "async def ")) and stripped.endswith(":"):
        return True
    return len(stripped) < 40 and len(replace_lines) >= 10

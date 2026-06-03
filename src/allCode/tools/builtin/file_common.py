"""Shared helpers for builtin file tools."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from allCode.workspace.path_resolver import safe_resolve_under_root

DEFAULT_READ_MAX_BYTES = 12_000
LARGE_FILE_BYTES = 20_000


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
        if count != 1:
            error_type = "patch_not_found" if count == 0 else "patch_ambiguous"
            raise PatchApplicationError(
                f"patch search must match exactly once, matched {count} times",
                error_type=error_type,
                match_count=count,
                search_preview=search[:240],
            )
        updated = updated.replace(search, replace, 1)
    return updated


def _low_context_large_replacement(search: str, replace: str) -> bool:
    search_lines = [line for line in search.splitlines() if line.strip()]
    replace_lines = [line for line in replace.splitlines() if line.strip()]
    if len(search_lines) > 1 or len(replace_lines) < 6:
        return False
    stripped = search_lines[0].strip()
    if stripped.startswith(("class ", "def ", "async def ")) and stripped.endswith(":"):
        return True
    return len(stripped) < 40 and len(replace_lines) >= 10

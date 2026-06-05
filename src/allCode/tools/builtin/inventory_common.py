"""Shared helpers for bounded read-only inventory tools."""

from __future__ import annotations

from pathlib import Path

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "cache",
    "coverage",
    "dist",
    "node_modules",
    "output",
    "review",
    "target",
}


def should_ignore_path(path: Path, *, include_hidden: bool = False) -> bool:
    for part in path.parts:
        if part in IGNORED_DIRS:
            return True
        if not include_hidden and part.startswith("."):
            return True
    return False


def path_metadata(path: Path, *, root: Path) -> dict[str, object]:
    try:
        stat = path.stat()
    except OSError:
        stat = None
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        relative = path.as_posix()
    return {
        "path": relative,
        "kind": "dir" if path.is_dir() else "file",
        "size": 0 if stat is None or path.is_dir() else stat.st_size,
        "mtime": None if stat is None else stat.st_mtime,
        "extension": "" if path.is_dir() else path.suffix.lower(),
    }

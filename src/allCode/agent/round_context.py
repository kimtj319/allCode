"""Small context helpers for round execution."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from allCode.core.models import ToolResult


def record_repair_context_reads(
    results: Sequence[ToolResult],
    repair_context_read_paths: set[str],
    *,
    workspace_root: str,
) -> None:
    for result in results:
        if result.name != "read_file" or not result.ok:
            continue
        raw_path = str(result.metadata.get("file_path") or "")
        if not raw_path:
            observation = result.metadata.get("observation")
            if isinstance(observation, dict):
                raw_path = str(observation.get("target") or "")
        normalized = normalize_round_path(raw_path, workspace_root=workspace_root)
        if normalized:
            repair_context_read_paths.add(normalized)


def normalize_round_path(path: str, *, workspace_root: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    candidate = Path(raw)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.expanduser().resolve().relative_to(Path(workspace_root).expanduser().resolve()).as_posix()
    except (OSError, ValueError):
        return candidate.as_posix()

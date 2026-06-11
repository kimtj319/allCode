"""Search/replace repair block parsing for generation workflow."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

from allCode.agent.task_plan import ProjectPlan
from allCode.core.models import TurnInput

SEARCH_MARKER = "<<<<<<< SEARCH"
REPLACE_MARKER = "======="
END_MARKER = ">>>>>>> REPLACE"


@dataclass(frozen=True)
class SearchReplaceBlock:
    path: str
    search: str
    replace: str


def search_replace_repairs(text: str, plan: ProjectPlan, turn_input: TurnInput) -> dict[str, str]:
    """Return full corrected file contents from Aider-style search/replace blocks."""

    allowed_paths = set(plan.required_paths())
    blocks = _extract_blocks(str(text or ""), allowed_paths=allowed_paths)
    if not blocks:
        return {}
    grouped: dict[str, list[SearchReplaceBlock]] = defaultdict(list)
    for block in blocks:
        grouped[block.path].append(block)

    target_root = Path(turn_input.workspace.root).expanduser() / plan.target_root
    repaired: dict[str, str] = {}
    for path, path_blocks in grouped.items():
        original = _read_existing(target_root / path)
        if original is None:
            continue
        updated = _apply_blocks(original, path_blocks)
        if updated is not None and updated != _normalize_newlines(original):
            repaired[path] = updated
    return repaired


def _extract_blocks(text: str, *, allowed_paths: set[str]) -> list[SearchReplaceBlock]:
    lines = _normalize_newlines(text).splitlines()
    blocks: list[SearchReplaceBlock] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != SEARCH_MARKER:
            index += 1
            continue
        path = _path_before_marker(lines, index, allowed_paths=allowed_paths)
        if path is None:
            index += 1
            continue
        replace_index = _find_marker(lines, REPLACE_MARKER, start=index + 1)
        end_index = _find_marker(lines, END_MARKER, start=(replace_index + 1 if replace_index >= 0 else index + 1))
        if replace_index < 0 or end_index < 0:
            index += 1
            continue
        search = _block_text(lines[index + 1 : replace_index])
        replace = _block_text(lines[replace_index + 1 : end_index])
        if search:
            blocks.append(SearchReplaceBlock(path=path, search=search, replace=replace))
        index = end_index + 1
    return blocks


def _path_before_marker(lines: list[str], marker_index: int, *, allowed_paths: set[str]) -> str | None:
    for candidate_index in range(marker_index - 1, max(-1, marker_index - 6), -1):
        candidate = lines[candidate_index].strip().strip("`")
        if not candidate or candidate.startswith("#") or candidate.startswith("```"):
            continue
        normalized = candidate.replace("\\", "/")
        if normalized in allowed_paths:
            return normalized
    return None


def _find_marker(lines: list[str], marker: str, *, start: int) -> int:
    for index in range(start, len(lines)):
        if lines[index].strip() == marker:
            return index
    return -1


def _block_text(lines: list[str]) -> str:
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return dedent("\n".join(lines))


def _read_existing(path: Path) -> str | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _apply_blocks(original: str, blocks: list[SearchReplaceBlock]) -> str | None:
    updated = _normalize_newlines(original)
    for block in blocks:
        search = _normalize_newlines(block.search)
        replace = _normalize_newlines(block.replace)
        if updated.count(search) != 1:
            return None
        updated = updated.replace(search, replace, 1)
    return updated


def _normalize_newlines(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")

"""Structured approval previews shared by tool execution and UIs."""

from __future__ import annotations

from typing import Literal

from allCode.core.models import CoreModel

PreviewKind = Literal["file_diff", "shell_command"]

DEFAULT_MAX_DIFF_LINES = 120
DEFAULT_MAX_DIFF_CHARS = 8000


class ApprovalPreview(CoreModel):
    kind: PreviewKind
    summary: str
    preview: str = ""
    target: str = ""
    action: str = ""
    added_lines: int = 0
    removed_lines: int = 0
    original_lines: int = 0
    shown_lines: int = 0
    original_chars: int = 0
    truncated: bool = False


def build_diff_preview(
    diff: str,
    *,
    target: str = "",
    action: str = "",
    max_lines: int = DEFAULT_MAX_DIFF_LINES,
    max_chars: int = DEFAULT_MAX_DIFF_CHARS,
) -> ApprovalPreview:
    """Return a bounded diff preview with line-count metadata."""

    lines = diff.splitlines()
    added, removed = _count_changed_lines(lines)
    clipped, truncated = _clip_lines_and_chars(lines, max_lines=max_lines, max_chars=max_chars)
    summary = _diff_summary(target=target, action=action, added_lines=added, removed_lines=removed, truncated=truncated)
    return ApprovalPreview(
        kind="file_diff",
        summary=summary,
        preview=clipped,
        target=target,
        action=action,
        added_lines=added,
        removed_lines=removed,
        original_lines=len(lines),
        shown_lines=len(clipped.splitlines()) if clipped else 0,
        original_chars=len(diff),
        truncated=truncated,
    )


def build_command_preview(command: str, *, validation: bool = False, max_chars: int = 1000) -> ApprovalPreview:
    clipped = command.strip()
    truncated = len(clipped) > max_chars
    if truncated:
        clipped = clipped[:max_chars].rstrip() + "\n... command truncated ..."
    action = "validation command" if validation else "shell command"
    return ApprovalPreview(
        kind="shell_command",
        summary=f"{action}: {clipped.splitlines()[0] if clipped else '(empty command)'}",
        preview=clipped,
        target=clipped,
        action=action,
        original_lines=len(command.splitlines()),
        shown_lines=len(clipped.splitlines()) if clipped else 0,
        original_chars=len(command),
        truncated=truncated,
    )


def _count_changed_lines(lines: list[str]) -> tuple[int, int]:
    added = 0
    removed = 0
    for line in lines:
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _clip_lines_and_chars(lines: list[str], *, max_lines: int, max_chars: int) -> tuple[str, bool]:
    safe_max_lines = max(1, max_lines)
    safe_max_chars = max(80, max_chars)
    clipped_lines = lines[:safe_max_lines]
    truncated = len(lines) > safe_max_lines
    clipped = "\n".join(clipped_lines)
    if len(clipped) > safe_max_chars:
        clipped = clipped[:safe_max_chars].rstrip()
        truncated = True
    if truncated:
        clipped = clipped.rstrip() + "\n... preview truncated ..."
    return clipped, truncated


def _diff_summary(*, target: str, action: str, added_lines: int, removed_lines: int, truncated: bool) -> str:
    target_label = target or "file"
    action_label = action or "file mutation"
    suffix = " · preview truncated" if truncated else ""
    return f"{action_label} {target_label}: +{added_lines}/-{removed_lines} lines{suffix}"

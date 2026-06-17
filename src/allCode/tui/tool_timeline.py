"""Compact terminal timeline rows for tool observations."""

from __future__ import annotations

from allCode.core.models import CoreModel, ToolResult


class ToolTimelineEntry(CoreModel):
    line: str = ""
    quiet_status: str = ""
    fold_title: str = ""
    fold_full_text: str = ""
    foldable: bool = False
    diff: str = ""


def build_tool_timeline_entry(result: ToolResult) -> ToolTimelineEntry:
    """Render one tool observation without leaking long raw output."""

    # The task plan is the one read-only tool whose output is meant to be seen:
    # render its checklist as a visible block rather than a folded one-liner.
    if result.name == "update_plan" and result.ok and (result.content or "").strip():
        return ToolTimelineEntry(line=result.content.rstrip())
    quiet_status = _quiet_readonly_tool_status(result)
    if quiet_status:
        return ToolTimelineEntry(quiet_status=quiet_status)
    status = "ok" if result.ok else result.error_type or "error"
    target = _tool_target(result)
    summary = _tool_summary(result)
    target_suffix = f" {target}" if target else ""
    summary_suffix = f" · {summary}" if summary else ""
    diff_body, added, removed = _edit_diff(result)
    # Show the +/- line counts on the summary row (Codex-style); the diff body
    # itself is rendered below so a code change is a visible diff, not plain text.
    stats_suffix = f" (+{added} -{removed})" if diff_body else ""
    line = f"• {result.name}{target_suffix} -> {status}{summary_suffix}{stats_suffix}"
    full_text = result.content or result.error or ""
    return ToolTimelineEntry(
        line=line,
        foldable=bool(full_text),
        fold_title=f"{result.name}: {status}",
        fold_full_text=full_text,
        diff=diff_body,
    )


def _edit_diff(result: ToolResult) -> tuple[str, int, int]:
    """Extract the unified-diff hunk body and +/- counts from a file edit.

    The file_write/file_patch tools record an ``EditTransaction`` whose ``diff``
    is a standard unified diff. We drop the ``---``/``+++`` file headers (the
    summary row already names the file) and keep the hunks for colored display.
    """
    if not result.ok:
        return "", 0, 0
    metadata = result.metadata or {}
    transaction = metadata.get("transaction")
    if not isinstance(transaction, dict):
        return "", 0, 0
    raw = transaction.get("diff")
    if not isinstance(raw, str) or not raw.strip():
        return "", 0, 0
    body_lines: list[str] = []
    added = 0
    removed = 0
    for diff_line in raw.splitlines():
        if diff_line.startswith("--- ") or diff_line.startswith("+++ "):
            continue
        if diff_line.startswith("+"):
            added += 1
        elif diff_line.startswith("-"):
            removed += 1
        body_lines.append(diff_line)
    return "\n".join(body_lines).strip("\n"), added, removed


def _tool_target(result: ToolResult) -> str:
    metadata = result.metadata or {}
    observation = metadata.get("observation")
    if isinstance(observation, dict) and observation.get("target"):
        return str(observation["target"])
    for key in ("file_path", "path", "query", "command"):
        value = metadata.get(key)
        if value:
            return str(value)
    return ""


def _tool_summary(result: ToolResult) -> str:
    metadata = result.metadata or {}
    observation = metadata.get("observation")
    if isinstance(observation, dict) and observation.get("summary"):
        return str(observation["summary"])
    if not result.ok and result.error:
        return result.error.splitlines()[0][:120]
    return ""


def _quiet_readonly_tool_status(result: ToolResult) -> str:
    if not result.ok:
        return ""
    if result.name == "read_file":
        return "대표 파일 확인 중"
    if result.name in {"list_tree", "glob_files", "list_directory", "search_files"}:
        return "코드 구조 확인 중"
    return ""

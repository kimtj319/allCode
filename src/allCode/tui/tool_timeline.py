"""Compact terminal timeline rows for tool observations."""

from __future__ import annotations

from allCode.core.models import CoreModel, ToolResult


class ToolTimelineEntry(CoreModel):
    line: str = ""
    quiet_status: str = ""
    fold_title: str = ""
    fold_full_text: str = ""
    foldable: bool = False


def build_tool_timeline_entry(result: ToolResult) -> ToolTimelineEntry:
    """Render one tool observation without leaking long raw output."""

    quiet_status = _quiet_readonly_tool_status(result)
    if quiet_status:
        return ToolTimelineEntry(quiet_status=quiet_status)
    status = "ok" if result.ok else result.error_type or "error"
    target = _tool_target(result)
    summary = _tool_summary(result)
    target_suffix = f" {target}" if target else ""
    summary_suffix = f" · {summary}" if summary else ""
    line = f"• {result.name}{target_suffix} -> {status}{summary_suffix}"
    full_text = result.content or result.error or ""
    return ToolTimelineEntry(
        line=line,
        foldable=bool(full_text),
        fold_title=f"{result.name}: {status}",
        fold_full_text=full_text,
    )


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

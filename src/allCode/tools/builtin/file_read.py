"""Builtin read_file tool."""

from __future__ import annotations

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.builtin.file_common import (
    DEFAULT_READ_MAX_BYTES,
    LARGE_FILE_BYTES,
    content_hash,
    read_text_if_exists,
    resolve_under_root,
)


class ReadFileTool:
    definition = ToolDefinition(
        name="read_file",
        description=(
            "Read a UTF-8 text file within the workspace. For large files, prefer start_line/end_line "
            "or max_bytes after search_files instead of reading the full file."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
                "max_bytes": {"type": "integer", "minimum": 1},
                "include_line_numbers": {"type": "boolean"},
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
        read_only=True,
        group="file",
        aliases=["cat"],
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            path = resolve_under_root(context.workspace.root, str(call.arguments["file_path"]))
            if not path.exists():
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    ok=False,
                    error=f"file does not exist: {path} (없음; 찾지 못했습니다)",
                    error_type="not_found",
                    metadata={
                        "file_path": str(path),
                        "observation": {"kind": "file_read", "target": str(path), "summary": f"File not found: {path.name}", "risk": "low"},
                    },
                )
            content = read_text_if_exists(path)
            max_bytes = int(call.arguments.get("max_bytes", DEFAULT_READ_MAX_BYTES))
            start_line = call.arguments.get("start_line")
            end_line = call.arguments.get("end_line")
            include_line_numbers = bool(call.arguments.get("include_line_numbers", False))
            all_lines = content.splitlines(keepends=True)
            content_bytes = len(content.encode("utf-8"))
            range_requested = start_line is not None or end_line is not None
            if content_bytes > LARGE_FILE_BYTES and not range_requested:
                return self._large_file_preview(call, path, content, all_lines, content_bytes)
            range_start = max(int(start_line or 1), 1)
            range_end = min(int(end_line or len(all_lines)), len(all_lines))
            selected = "".join(all_lines[range_start - 1 : range_end])
            selected, truncated = self._truncate(selected, max_bytes)
            if include_line_numbers:
                selected = "\n".join(f"{offset}: {line}" for offset, line in enumerate(selected.splitlines(), start=range_start))
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=True,
                content=selected,
                metadata={
                    "file_path": str(path),
                    "content_hash": content_hash(content),
                    "line_count": len(all_lines),
                    "full_size_bytes": content_bytes,
                    "returned_range": [range_start, range_end],
                    "truncated": truncated,
                    "range_first_recommended": content_bytes > LARGE_FILE_BYTES and not range_requested,
                    "observation": {
                        "kind": "file_read",
                        "target": str(path),
                        "summary": f"Read {path.name}",
                        "risk": "low",
                    },
                },
            )
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)

    @staticmethod
    def _large_file_preview(call: ToolCall, path, content: str, all_lines: list[str], content_bytes: int) -> ToolResult:
        preview_lines = "".join(all_lines[: min(20, len(all_lines))])
        selected = (
            f"[large file: {content_bytes} bytes, {len(all_lines)} lines]\n"
            "Use search_files first, then read_file with start_line/end_line for the relevant range.\n\n"
            f"[first lines preview]\n{preview_lines}".rstrip()
        )
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=selected,
            metadata={
                "file_path": str(path),
                "content_hash": content_hash(content),
                "line_count": len(all_lines),
                "full_size_bytes": content_bytes,
                "returned_range": [1, min(20, len(all_lines))],
                "truncated": True,
                "range_first_required": True,
                "range_first_recommended": True,
                "observation": {
                    "kind": "file_read",
                    "target": str(path),
                    "summary": f"Large file preview only: {path.name}; use search_files and ranged read_file",
                    "risk": "low",
                },
            },
        )

    @staticmethod
    def _truncate(selected: str, max_bytes: int) -> tuple[str, bool]:
        encoded = selected.encode("utf-8")
        if len(encoded) <= max_bytes:
            return selected, False
        truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
        return (
            truncated.rstrip()
            + "\n\n[truncated: use search_files plus read_file start_line/end_line or max_bytes to inspect a precise range]",
            True,
        )

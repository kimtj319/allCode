"""Builtin workspace search tool."""

from __future__ import annotations

from pathlib import Path

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.builtin.file_ops import resolve_under_root

IGNORED_DIRS = {".git", ".venv", "node_modules", "dist", "build", "target", "__pycache__"}


class SearchFilesTool:
    definition = ToolDefinition(
        name="search_files",
        description="Search UTF-8 workspace files for a literal query.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        read_only=True,
        group="search",
        aliases=["rg"],
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            query = str(call.arguments["query"])
            max_results = int(call.arguments.get("max_results", 50))
            root = resolve_under_root(context.workspace.root, str(call.arguments.get("path", ".")))
            rows: list[str] = []
            for path in self._iter_files(root):
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if query in line:
                        rows.append(f"{path}:{line_number}: {line}")
                        if len(rows) >= max_results:
                            return self._result(call, rows)
            return self._result(call, rows)
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)

    def _iter_files(self, root: Path):
        if root.is_file():
            yield root
            return
        for path in root.rglob("*"):
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            if path.is_file():
                yield path

    def _result(self, call: ToolCall, rows: list[str]) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content="\n".join(rows),
            metadata={"evidence_count": len(rows)},
        )

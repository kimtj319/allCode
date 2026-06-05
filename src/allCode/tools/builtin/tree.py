"""Bounded read-only tree inventory tool."""

from __future__ import annotations

from pathlib import Path

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.builtin.file_common import resolve_under_root
from allCode.tools.builtin.inventory_common import path_metadata, should_ignore_path


class ListTreeTool:
    definition = ToolDefinition(
        name="list_tree",
        description="List a compact bounded directory tree with structured metadata.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_depth": {"type": "integer"},
                "max_entries": {"type": "integer"},
                "include_hidden": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        read_only=True,
        group="file",
        aliases=["tree"],
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            root = resolve_under_root(context.workspace.root, str(call.arguments.get("path", ".")))
            if not root.exists() or not root.is_dir():
                return ToolResult(call_id=call.id, name=call.name, ok=False, error=f"not a directory: {root}", error_type="not_directory")
            workspace_root = Path(context.workspace.root).expanduser().resolve()
            max_depth = min(max(1, int(call.arguments.get("max_depth", 2))), 5)
            max_entries = min(max(1, int(call.arguments.get("max_entries", 160))), 500)
            include_hidden = bool(call.arguments.get("include_hidden", False))
            rows: list[dict[str, object]] = []
            lines: list[str] = []
            omitted = 0
            for path in _walk_bounded(root, workspace_root=workspace_root, max_depth=max_depth, include_hidden=include_hidden):
                if len(rows) >= max_entries:
                    omitted += 1
                    continue
                metadata = path_metadata(path, root=workspace_root)
                try:
                    depth = len(path.relative_to(root).parts)
                except ValueError:
                    depth = 0
                metadata["depth"] = depth
                rows.append(metadata)
                prefix = "  " * max(0, depth - 1)
                marker = "/" if path.is_dir() else ""
                lines.append(f"{prefix}{path.name}{marker}")
            truncated = omitted > 0
            if truncated:
                lines.append(f"[{omitted} entries truncated]")
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=True,
                content="\n".join(lines) if lines else "(empty directory)",
                metadata={
                    "path": str(root),
                    "entries": rows,
                    "entry_count": len(rows),
                    "truncated": truncated,
                    "omitted_count": omitted,
                    "next_suggested_tool": "source_overview" if truncated else "read_file",
                    "observation": {
                        "kind": "tree",
                        "target": str(root),
                        "summary": f"Listed {len(rows)} entries under {root.name}",
                        "risk": "low",
                    },
                },
            )
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)


def _walk_bounded(root: Path, *, workspace_root: Path, max_depth: int, include_hidden: bool) -> list[Path]:
    paths: list[Path] = []

    def visit(path: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = sorted(path.iterdir(), key=lambda child: (not child.is_dir(), child.name.lower()))
        except OSError:
            return
        for child in children:
            try:
                relative = child.relative_to(workspace_root)
            except ValueError:
                continue
            if should_ignore_path(relative, include_hidden=include_hidden):
                continue
            paths.append(child)
            if child.is_dir():
                visit(child, depth + 1)

    visit(root, 1)
    return paths

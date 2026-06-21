"""Bounded read-only glob inventory tool."""

from __future__ import annotations

from pathlib import Path

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.builtin.file_common import resolve_under_root
from allCode.tools.builtin.inventory_common import path_metadata, should_ignore_path


class GlobFilesTool:
    definition = ToolDefinition(
        name="glob_files",
        description="Find workspace files matching a glob pattern without reading file contents.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
                "max_results": {"type": "integer"},
                "include_dirs": {"type": "boolean"},
                "include_hidden": {"type": "boolean"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        read_only=True,
        group="search",
        aliases=["glob"],
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            pattern = str(call.arguments.get("pattern", "")).strip()
            if not pattern:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    ok=False,
                    error="glob_files requires a non-empty pattern.",
                    error_type="invalid_pattern",
                    metadata={"invalid_pattern": True},
                )
            root = resolve_under_root(context.workspace.root, str(call.arguments.get("path", ".")))
            workspace_root = Path(context.workspace.root).expanduser().resolve()
            max_results = min(max(1, int(call.arguments.get("max_results", 100))), 300)
            include_dirs = bool(call.arguments.get("include_dirs", False))
            include_hidden = bool(call.arguments.get("include_hidden", False))
            matches: list[Path] = []
            omitted = 0
            for path in sorted(root.glob(pattern)):
                # Ignore-check relative to the REQUESTED root, not the workspace
                # root: when the user explicitly globs inside a hidden/ignored
                # dir (e.g. path=".github"), the leading ".github" prefix must
                # not filter out every match. Hidden/ignored SUBdirs under the
                # requested root are still skipped.
                if should_ignore_path(path.relative_to(root), include_hidden=include_hidden):
                    continue
                if path.is_dir() and not include_dirs:
                    continue
                if not path.is_file() and not path.is_dir():
                    continue
                if len(matches) >= max_results:
                    omitted += 1
                    continue
                matches.append(path)
            rows = [path_metadata(path, root=workspace_root) for path in matches]
            content = "\n".join(str(row["path"]) for row in rows)
            if not content:
                content = f"No files matched pattern {pattern!r}."
            truncated = omitted > 0
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=True,
                content=content,
                metadata={
                    "pattern": pattern,
                    "path": str(root),
                    "results": rows,
                    "evidence_count": len(rows),
                    "truncated": truncated,
                    "omitted_count": omitted,
                    "observation": {
                        "kind": "glob",
                        "target": str(root),
                        "summary": f"Matched {len(rows)} path(s) for {pattern!r}",
                        "risk": "low",
                    },
                },
            )
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)

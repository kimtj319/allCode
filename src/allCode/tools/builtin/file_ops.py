"""Builtin file operation tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.diff import EditTransaction
from allCode.workspace.path_resolver import safe_resolve_under_root


def resolve_under_root(root: str, file_path: str) -> Path:
    return safe_resolve_under_root(root, file_path)


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    if not path.is_file():
        raise ValueError(f"path is not a file: {path}")
    return path.read_text(encoding="utf-8")


class ListDirectoryTool:
    definition = ToolDefinition(
        name="list_directory",
        description="List files and directories below a workspace path.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "additionalProperties": False,
        },
        read_only=True,
        group="file",
        aliases=["ls"],
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            path = resolve_under_root(context.workspace.root, str(call.arguments.get("path", ".")))
            if not path.exists() or not path.is_dir():
                return ToolResult(call_id=call.id, name=call.name, ok=False, error=f"not a directory: {path}")
            rows = []
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                kind = "dir" if child.is_dir() else "file"
                rows.append(f"{kind}\t{child.name}")
            return ToolResult(call_id=call.id, name=call.name, ok=True, content="\n".join(rows))
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)


class ReadFileTool:
    definition = ToolDefinition(
        name="read_file",
        description="Read a UTF-8 text file within the workspace.",
        parameters={
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
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
            content = read_text_if_exists(path)
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=True,
                content=content,
                metadata={"file_path": str(path)},
            )
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)


class WriteFileTool:
    definition = ToolDefinition(
        name="write_file",
        description="Create or replace a UTF-8 text file within the writable workspace.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["file_path", "content"],
            "additionalProperties": False,
        },
        read_only=False,
        requires_approval=True,
        group="file",
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            path = resolve_under_root(context.workspace.root, str(call.arguments["file_path"]))
            content = str(call.arguments["content"])
            before = read_text_if_exists(path)
            action = "created" if not path.exists() else "modified"
            transaction = EditTransaction.from_contents(path=path, before=before, after=content, action=action)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=True,
                content=f"{action}: {path}",
                metadata={
                    "transaction": transaction.model_dump(mode="json"),
                    "created_files": [str(path)] if action == "created" else [],
                    "changed_files": [str(path)],
                },
            )
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)


class PatchFileTool:
    definition = ToolDefinition(
        name="patch_file",
        description="Patch a file with exact search/replace blocks.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "patches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "search": {"type": "string"},
                            "replace": {"type": "string"},
                        },
                        "required": ["search", "replace"],
                    },
                },
            },
            "required": ["file_path", "patches"],
            "additionalProperties": False,
        },
        read_only=False,
        requires_approval=True,
        group="file",
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            path = resolve_under_root(context.workspace.root, str(call.arguments["file_path"]))
            before = read_text_if_exists(path)
            after = self._apply_patches(before, call.arguments.get("patches", []))
            transaction = EditTransaction.from_contents(path=path, before=before, after=after, action="modified")
            path.write_text(after, encoding="utf-8")
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=True,
                content=f"patched: {path}",
                metadata={
                    "transaction": transaction.model_dump(mode="json"),
                    "changed_files": [str(path)],
                },
            )
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)

    def _apply_patches(self, content: str, patches: Any) -> str:
        if not isinstance(patches, list) or not patches:
            raise ValueError("patches must be a non-empty list")
        updated = content
        for patch in patches:
            if not isinstance(patch, dict):
                raise ValueError("each patch must be an object")
            search = str(patch.get("search", ""))
            replace = str(patch.get("replace", ""))
            count = updated.count(search)
            if count != 1:
                raise ValueError(f"patch search must match exactly once, matched {count} times")
            updated = updated.replace(search, replace, 1)
        return updated


def file_tools() -> list:
    return [ListDirectoryTool(), ReadFileTool(), WriteFileTool(), PatchFileTool()]

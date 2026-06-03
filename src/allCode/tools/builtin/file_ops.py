"""Builtin file operation tools."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.builtin.file_common import (
    PatchApplicationError,
    apply_exact_patches,
    content_hash,
    read_text_if_exists,
    resolve_under_root,
)
from allCode.tools.builtin.file_read import ReadFileTool
from allCode.tools.diff import EditTransaction


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


class WriteFileTool:
    definition = ToolDefinition(
        name="write_file",
        description="Create or replace a UTF-8 text file within the writable workspace.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content": {"type": "string"},
                "create_only": {"type": "boolean"},
                "overwrite": {"type": "boolean"},
                "expected_hash": {"type": "string"},
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
            if call.arguments.get("create_only") and path.exists():
                return ToolResult(call_id=call.id, name=call.name, ok=False, error=f"file already exists: {path}", error_type="file_exists")
            if call.arguments.get("overwrite") is False and path.exists():
                return ToolResult(call_id=call.id, name=call.name, ok=False, error=f"overwrite disabled for existing file: {path}", error_type="overwrite_denied")
            expected_hash = call.arguments.get("expected_hash")
            if expected_hash and before and str(expected_hash) != content_hash(before):
                return ToolResult(call_id=call.id, name=call.name, ok=False, error="expected_hash does not match current file content", error_type="stale_file")
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
                    "observation": {
                        "kind": "file_write",
                        "target": str(path),
                        "summary": f"{action}: {path.name}",
                        "risk": "medium",
                    },
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
                "expected_hash": {"type": "string"},
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
            expected_hash = call.arguments.get("expected_hash")
            if expected_hash and str(expected_hash) != content_hash(before):
                return ToolResult(call_id=call.id, name=call.name, ok=False, error="expected_hash does not match current file content", error_type="stale_file")
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
                    "observation": {
                        "kind": "file_patch",
                        "target": str(path),
                        "summary": f"patched: {path.name}",
                        "risk": "medium",
                    },
                },
            )
        except PatchApplicationError as exc:
            path_text = str(call.arguments.get("file_path", ""))
            try:
                path_text = str(resolve_under_root(context.workspace.root, path_text))
            except Exception:
                pass
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=str(exc),
                error_type=exc.error_type,
                metadata=exc.metadata(file_path=path_text),
            )
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)

    def _apply_patches(self, content: str, patches: Any) -> str:
        return apply_exact_patches(content, patches)


class DeletePathTool:
    definition = ToolDefinition(
        name="delete_path",
        description="Delete a workspace file safely, optionally moving it to .allCode/trash.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "recursive": {"type": "boolean"},
                "expected_hash": {"type": "string"},
                "move_to_trash": {"type": "boolean"},
                "missing_ok": {"type": "boolean"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        read_only=False,
        requires_approval=True,
        group="file",
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            target = resolve_under_root(context.workspace.root, str(call.arguments["path"]))
            root = Path(context.workspace.root).expanduser().resolve()
            if target == root or target.name == ".git" or target == Path.home().expanduser().resolve():
                return ToolResult(call_id=call.id, name=call.name, ok=False, error=f"refusing to delete protected path: {target}", error_type="protected_path")
            missing_ok = bool(call.arguments.get("missing_ok", False))
            if not target.exists() and missing_ok:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    ok=True,
                    content=f"not found; no deletion performed: {target}",
                    metadata={
                        "safe_noop": True,
                        "noop_reason": "target_not_found",
                        "noop_targets": [str(target)],
                        "observation": {
                            "kind": "file_delete",
                            "target": str(target),
                            "summary": f"not found; no deletion performed: {target.name}",
                            "risk": "low",
                        },
                    },
                )
            if not target.exists():
                return ToolResult(call_id=call.id, name=call.name, ok=False, error=f"path does not exist: {target}", error_type="not_found")
            recursive = bool(call.arguments.get("recursive", False))
            if target.is_dir() and not recursive:
                return ToolResult(call_id=call.id, name=call.name, ok=False, error="directory deletion requires recursive=true", error_type="recursive_required")
            if target.is_file():
                expected_hash = call.arguments.get("expected_hash")
                before = read_text_if_exists(target)
                if expected_hash and str(expected_hash) != content_hash(before):
                    return ToolResult(call_id=call.id, name=call.name, ok=False, error="expected_hash does not match current file content", error_type="stale_file")
            move_to_trash = bool(call.arguments.get("move_to_trash", True))
            trash_path = None
            if move_to_trash:
                trash_dir = root / ".allCode" / "trash"
                trash_dir.mkdir(parents=True, exist_ok=True)
                trash_path = trash_dir / f"{call.id}-{target.name}"
                shutil.move(str(target), str(trash_path))
            elif target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=True,
                content=f"deleted: {target}",
                metadata={
                    "deleted_files": [str(target)],
                    "trash_path": str(trash_path) if trash_path is not None else None,
                    "observation": {
                        "kind": "file_delete",
                        "target": str(target),
                        "summary": f"deleted: {target.name}",
                        "risk": "high" if recursive else "medium",
                    },
                },
            )
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)


def file_tools() -> list:
    return [ListDirectoryTool(), ReadFileTool(), WriteFileTool(), PatchFileTool(), DeletePathTool()]

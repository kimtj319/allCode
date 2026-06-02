"""Builtin file operation tools."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
from typing import Any

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.diff import EditTransaction
from allCode.workspace.path_resolver import safe_resolve_under_root

DEFAULT_READ_MAX_BYTES = 12_000
LARGE_FILE_BYTES = 20_000


class PatchApplicationError(ValueError):
    """Structured patch failure with tool-result metadata."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        match_count: int | None = None,
        search_preview: str = "",
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.match_count = match_count
        self.search_preview = search_preview

    def metadata(self, *, file_path: str) -> dict[str, Any]:
        return {
            "file_path": file_path,
            "match_count": self.match_count,
            "search_preview": self.search_preview,
            "recommended_next_tools": ["read_file", "write_file"] if self.error_type == "patch_ambiguous" else ["read_file", "patch_file"],
            "must_not_repeat_same_patch": True,
            "observation": {
                "kind": "patch_failure",
                "target": file_path,
                "summary": str(self),
                "risk": "low",
            },
        }


def resolve_under_root(root: str, file_path: str) -> Path:
    return safe_resolve_under_root(root, file_path)


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    if not path.is_file():
        raise ValueError(f"path is not a file: {path}")
    return path.read_text(encoding="utf-8")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply_exact_patches(content: str, patches: Any) -> str:
    if not isinstance(patches, list) or not patches:
        raise PatchApplicationError(
            "patches must be a non-empty list",
            error_type="patch_invalid_request",
        )
    updated = content
    for patch in patches:
        if not isinstance(patch, dict):
            raise PatchApplicationError(
                "each patch must be an object",
                error_type="patch_invalid_request",
            )
        search = str(patch.get("search", ""))
        replace = str(patch.get("replace", ""))
        if not search:
            raise PatchApplicationError(
                "patch search must be a non-empty string",
                error_type="patch_invalid_request",
                match_count=0,
            )
        count = updated.count(search)
        if count != 1:
            error_type = "patch_not_found" if count == 0 else "patch_ambiguous"
            raise PatchApplicationError(
                f"patch search must match exactly once, matched {count} times",
                error_type=error_type,
                match_count=count,
                search_preview=search[:240],
            )
        updated = updated.replace(search, replace, 1)
    return updated


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
                        "observation": {
                            "kind": "file_read",
                            "target": str(path),
                            "summary": f"File not found: {path.name}",
                            "risk": "low",
                        },
                    },
                )
            content = read_text_if_exists(path)
            max_bytes = int(call.arguments.get("max_bytes", DEFAULT_READ_MAX_BYTES))
            start_line = call.arguments.get("start_line")
            end_line = call.arguments.get("end_line")
            include_line_numbers = bool(call.arguments.get("include_line_numbers", False))
            all_lines = content.splitlines(keepends=True)
            selected_lines = all_lines
            range_start = 1
            range_end = len(all_lines)
            content_bytes = len(content.encode("utf-8"))
            range_requested = start_line is not None or end_line is not None
            range_first_required = content_bytes > LARGE_FILE_BYTES and not range_requested
            if range_first_required:
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
            if start_line is not None or end_line is not None:
                range_start = max(int(start_line or 1), 1)
                range_end = min(int(end_line or len(all_lines)), len(all_lines))
                selected_lines = all_lines[range_start - 1 : range_end]
            selected = "".join(selected_lines)
            encoded = selected.encode("utf-8")
            truncated = len(encoded) > max_bytes
            if truncated:
                selected = encoded[:max_bytes].decode("utf-8", errors="replace")
                selected = (
                    selected.rstrip()
                    + "\n\n[truncated: use search_files plus read_file start_line/end_line or max_bytes to inspect a precise range]"
                )
            range_first_recommended = content_bytes > LARGE_FILE_BYTES and not range_requested
            if include_line_numbers:
                numbered = []
                for offset, line in enumerate(selected.splitlines(), start=range_start):
                    numbered.append(f"{offset}: {line}")
                selected = "\n".join(numbered)
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
                    "range_first_recommended": range_first_recommended,
                    "observation": {
                        "kind": "file_read",
                        "target": str(path),
                        "summary": (
                            f"Read {path.name}; large file, use ranged reads for more detail"
                            if range_first_recommended
                            else f"Read {path.name}"
                        ),
                        "risk": "low",
                    },
                },
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

"""AST-aware symbol editing and multi-file atomic edits.

``replace_symbol`` swaps a whole Python function/class definition by name —
the model supplies the new definition and we locate the old one with ``ast``,
so there is no fragile whitespace-exact search/replace. ``apply_edits`` writes
several files as one transaction: every file is validated after the write and,
if any file ends up broken (or any write fails), all files are restored to
their original contents. This gives the atomic, conflict-aware multi-file edit
that line-based patching lacks.
"""

from __future__ import annotations

import ast
from pathlib import Path

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.builtin.file_common import read_text_if_exists, resolve_under_root, syntax_warning
from allCode.tools.diff import EditTransaction


def _find_symbol_span(source: str, symbol: str) -> tuple[int, int, str] | None:
    """Return (start_line, end_line, indent) 1-based inclusive for a top-level
    or dotted ``Class.method`` definition, or None."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    parts = symbol.split(".")

    def _find(body: list[ast.stmt], names: list[str]):
        head, rest = names[0], names[1:]
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == head:
                if not rest:
                    return node
                if isinstance(node, ast.ClassDef):
                    return _find(node.body, rest)
                return None
        return None

    node = _find(tree.body, parts)
    if node is None or node.end_lineno is None:
        return None
    # Include any decorators that sit above the def.
    start = node.lineno
    for decorator in getattr(node, "decorator_list", []):
        start = min(start, decorator.lineno)
    indent = " " * node.col_offset
    return start, node.end_lineno, indent


class ReplaceSymbolTool:
    definition = ToolDefinition(
        name="replace_symbol",
        description=(
            "Replace a whole Python function/class definition by name (e.g. 'parse' or "
            "'Service.run') with new source. Locates the target with the AST — no exact "
            "whitespace match needed — and rejects the edit if the result does not parse."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "symbol": {"type": "string", "description": "Function/class name, dotted for methods."},
                "new_source": {"type": "string", "description": "The replacement definition (full def/class)."},
            },
            "required": ["file_path", "symbol", "new_source"],
            "additionalProperties": False,
        },
        read_only=False,
        requires_approval=True,
        group="file",
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            path = resolve_under_root(context.workspace.root, str(call.arguments["file_path"]))
            symbol = str(call.arguments["symbol"]).strip()
            new_source = str(call.arguments["new_source"])
            before = read_text_if_exists(path)
            if not before:
                return ToolResult(call_id=call.id, name=call.name, ok=False, error=f"file not found or empty: {path}", error_type="not_found")
            span = _find_symbol_span(before, symbol)
            if span is None:
                return ToolResult(call_id=call.id, name=call.name, ok=False, error=f"symbol not found: {symbol}", error_type="symbol_not_found")
            start, end, _indent = span
            lines = before.splitlines(keepends=True)
            replacement = new_source if new_source.endswith("\n") else new_source + "\n"
            after = "".join(lines[: start - 1]) + replacement + "".join(lines[end:])
            warning = syntax_warning(path, after)
            if warning:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    ok=False,
                    error=f"edit rejected — result would not parse: {warning}",
                    error_type="syntax_error",
                )
            transaction = EditTransaction.from_contents(path=path, before=before, after=after, action="modified")
            path.write_text(after, encoding="utf-8")
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=True,
                content=f"replaced symbol {symbol} in {path}",
                metadata={
                    "transaction": transaction.model_dump(mode="json"),
                    "changed_files": [str(path)],
                    "symbol": symbol,
                    "observation": {"kind": "symbol_replace", "target": str(path), "summary": f"replace {symbol}", "risk": "medium"},
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)


class ApplyEditsTool:
    definition = ToolDefinition(
        name="apply_edits",
        description=(
            "Apply multiple whole-file writes as one atomic transaction. Every file is "
            "validated after writing; if any file fails to parse or any write errors, ALL "
            "files are rolled back to their original contents. Use for coordinated multi-file changes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["file_path", "content"],
                    },
                }
            },
            "required": ["edits"],
            "additionalProperties": False,
        },
        read_only=False,
        requires_approval=True,
        group="file",
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        edits = call.arguments.get("edits")
        if not isinstance(edits, list) or not edits:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error="edits must be a non-empty list", error_type="invalid_request")

        snapshots: list[tuple[Path, str | None]] = []  # (path, original content or None if it did not exist)
        written: list[Path] = []
        try:
            for edit in edits:
                if not isinstance(edit, dict) or "file_path" not in edit or "content" not in edit:
                    raise ValueError("each edit needs file_path and content")
                path = resolve_under_root(context.workspace.root, str(edit["file_path"]))
                original = path.read_text(encoding="utf-8") if path.exists() else None
                snapshots.append((path, original))

            changed: list[str] = []
            created: list[str] = []
            for (path, original), edit in zip(snapshots, edits):
                content = str(edit["content"])
                warning = syntax_warning(path, content)
                if warning:
                    raise _AtomicEditError(f"{path.name}: {warning}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                written.append(path)
                (created if original is None else changed).append(str(path))

            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=True,
                content=f"applied {len(edits)} file edits atomically",
                metadata={
                    "created_files": created,
                    "changed_files": changed + created,
                    "observation": {"kind": "atomic_edit", "target": f"{len(edits)} files", "summary": "apply_edits", "risk": "medium"},
                },
            )
        except Exception as exc:  # noqa: BLE001 - roll back everything on any failure
            self._rollback(snapshots, written)
            error_type = "atomic_edit_rejected" if isinstance(exc, _AtomicEditError) else exc.__class__.__name__
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=f"atomic edit rolled back: {exc}",
                error_type=error_type,
                metadata={"rolled_back": True},
            )

    @staticmethod
    def _rollback(snapshots: list[tuple[Path, str | None]], written: list[Path]) -> None:
        written_set = set(written)
        for path, original in snapshots:
            if path not in written_set:
                continue
            try:
                if original is None:
                    if path.exists():
                        path.unlink()
                else:
                    path.write_text(original, encoding="utf-8")
            except OSError:
                continue


class _AtomicEditError(ValueError):
    """A validated-write failure that should trigger a full rollback."""

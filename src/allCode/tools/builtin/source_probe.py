"""Bounded source probe tool for symbol/range-grounded inspection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.memory.redaction import redact_data, redact_text
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.builtin.file_common import LARGE_FILE_BYTES, content_hash, read_text_if_exists, resolve_under_root
from allCode.tools.builtin.source_probe_edges import enriched_outgoing_edges
from allCode.workspace.source_intelligence import SourceFileAnalysis, SourceIntelligenceService, SourceSymbol

MAX_SYMBOL_SPAN_LINES = 32
MAX_CHILD_SIGNATURES_PER_WIDE_SYMBOL = 4
# Wide-symbol body samples drive behavior-level (not just import-level) analysis,
# so give the model enough of a key method to describe what it actually does.
MAX_BODY_SAMPLE_LINES = 18


@dataclass(frozen=True)
class ProbeRange:
    start: int
    end: int
    reason: str
    symbol: str = ""


class SourceProbeTool:
    definition = ToolDefinition(
        name="source_probe",
        description=(
            "Inspect bounded source slices around imports and symbols without dumping whole file bodies. "
            "Use this before read_file for broad source analysis."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "symbols": {"type": "array", "items": {"type": "string"}},
                "max_ranges": {"type": "integer", "minimum": 1},
                "context_lines": {"type": "integer", "minimum": 0},
                "include_imports": {"type": "boolean"},
                "include_edges": {"type": "boolean"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        read_only=True,
        group="search",
        aliases=["probe_source"],
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            workspace_root = Path(context.workspace.root).expanduser().resolve()
            path = resolve_under_root(workspace_root, str(call.arguments["path"]))
            if not path.exists() or not path.is_file():
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    ok=False,
                    error=f"file does not exist: {path}",
                    error_type="not_found",
                    metadata={
                        "file_path": str(path),
                        "observation": {"kind": "source_probe", "target": str(path), "summary": "File not found", "risk": "low"},
                    },
                )
            content = read_text_if_exists(path)
            content_bytes = len(content.encode("utf-8"))
            if content_bytes > LARGE_FILE_BYTES * 2:
                return self._large_file_result(call, path, workspace_root, content, content_bytes)

            analysis = SourceIntelligenceService().analyze_text(path=path, text=content)
            symbols = [str(item) for item in call.arguments.get("symbols", []) if str(item).strip()]
            max_ranges = min(max(1, int(call.arguments.get("max_ranges", 4))), 8)
            context_lines = min(max(0, int(call.arguments.get("context_lines", 2))), 6)
            include_imports = bool(call.arguments.get("include_imports", True))
            include_edges = bool(call.arguments.get("include_edges", True))
            ranges, wide_symbols = _select_ranges(
                analysis,
                requested_symbols=symbols,
                line_count=len(content.splitlines()),
                max_ranges=max_ranges,
                context_lines=context_lines,
                include_imports=include_imports,
            )
            rendered = _render_ranges(path, workspace_root, content, ranges)
            observation = _observation(
                path=path,
                workspace_root=workspace_root,
                analysis=analysis,
                ranges=ranges,
                include_edges=include_edges,
                truncated=len(ranges) >= max_ranges,
                wide_symbols=wide_symbols,
            )
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=True,
                content=redact_text(rendered),
                metadata=redact_data(
                    {
                        "file_path": str(path),
                        "content_hash": content_hash(content),
                        "line_count": len(content.splitlines()),
                        "full_size_bytes": content_bytes,
                        "returned_ranges": [range_item.__dict__ for range_item in ranges],
                        "truncated": len(ranges) >= max_ranges,
                        "backend": analysis.backend,
                        "observation": observation,
                    }
                ),
            )
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)

    @staticmethod
    def _large_file_result(call: ToolCall, path: Path, workspace_root: Path, content: str, content_bytes: int) -> ToolResult:
        relative = _relative(path, workspace_root)
        summary = (
            f"Source probe for {relative}: file is too large for full AST probing "
            f"({content_bytes} bytes). Use search_files and ranged read_file."
        )
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=summary,
            metadata={
                "file_path": str(path),
                "content_hash": content_hash(content),
                "full_size_bytes": content_bytes,
                "truncated": True,
                "range_first_required": True,
                "observation": {
                    "kind": "source_probe",
                    "target": relative,
                    "summary": "Large source file; probe returned metadata only",
                    "risk": "low",
                    "truncated": True,
                },
            },
        )


def _select_ranges(
    analysis: SourceFileAnalysis,
    *,
    requested_symbols: list[str],
    line_count: int,
    max_ranges: int,
    context_lines: int,
    include_imports: bool,
) -> tuple[list[ProbeRange], list[dict[str, object]]]:
    ranges: list[ProbeRange] = []
    child_sample_ranges: list[ProbeRange] = []
    wide_symbols: list[dict[str, object]] = []
    if include_imports and analysis.imports:
        lines = [item.line for item in analysis.imports if item.line > 0]
        if lines:
            ranges.append(_bounded_range(min(lines), max(lines), line_count, context_lines=0, reason="imports"))

    matched_symbols = _matching_symbols(analysis.symbols, requested_symbols)
    if not matched_symbols:
        matched_symbols = [symbol for symbol in analysis.symbols if symbol.exported][:max_ranges]
    for symbol in matched_symbols:
        if len(ranges) >= max_ranges:
            break
        range_item, wide = _range_for_symbol(symbol, line_count=line_count, context_lines=context_lines)
        ranges.append(range_item)
        if wide:
            wide_symbols.append(wide)
            child_sample_ranges.extend(
                _wide_symbol_body_sample_ranges(
                    symbol,
                    header_range=range_item,
                    line_count=line_count,
                    limit=1,
                )
            )
            child_sample_ranges.extend(
                _child_body_sample_ranges(
                    analysis.symbols,
                    parent=symbol,
                    line_count=line_count,
                    limit=MAX_CHILD_SIGNATURES_PER_WIDE_SYMBOL,
                )
            )
    for range_item in child_sample_ranges:
        if len(ranges) >= max_ranges:
            break
        ranges.append(range_item)
    return _merge_ranges(ranges)[:max_ranges], wide_symbols[:8]


def _range_for_symbol(
    symbol: SourceSymbol,
    *,
    line_count: int,
    context_lines: int,
) -> tuple[ProbeRange, dict[str, object] | None]:
    start = symbol.line or 1
    raw_end = symbol.end_line or symbol.line or start
    span = max(1, raw_end - start + 1)
    if span <= MAX_SYMBOL_SPAN_LINES:
        return (
            _bounded_range(
                start,
                raw_end,
                line_count,
                context_lines=context_lines,
                reason="symbol",
                symbol=symbol.scope or symbol.name,
            ),
            None,
        )
    capped_end = min(line_count, start + MAX_SYMBOL_SPAN_LINES - 1)
    return (
        _bounded_range(
            start,
            capped_end,
            line_count,
            context_lines=0,
            reason="symbol_header",
            symbol=symbol.scope or symbol.name,
        ),
        {
            "symbol": symbol.scope or symbol.name,
            "kind": symbol.kind,
            "line": start,
            "end_line": raw_end,
            "span_lines": span,
            "summary": "large symbol; header, bounded body sample, and child body samples only",
        },
    )


def _wide_symbol_body_sample_ranges(
    symbol: SourceSymbol,
    *,
    header_range: ProbeRange,
    line_count: int,
    limit: int,
) -> list[ProbeRange]:
    raw_end = symbol.end_line or symbol.line or header_range.end
    sample_start = header_range.end + 1
    if sample_start > raw_end:
        return []
    sample_end = min(raw_end, sample_start + MAX_BODY_SAMPLE_LINES - 1)
    return [
        _bounded_range(
            sample_start,
            sample_end,
            line_count,
            context_lines=0,
            reason="symbol_body_sample",
            symbol=symbol.scope or symbol.name,
        )
    ][:limit]


def _child_body_sample_ranges(
    symbols: list[SourceSymbol],
    *,
    parent: SourceSymbol,
    line_count: int,
    limit: int,
) -> list[ProbeRange]:
    parent_scope = parent.scope or parent.name
    if not parent_scope:
        return []
    ranges: list[ProbeRange] = []
    for child in sorted(symbols, key=lambda item: item.line or 0):
        if child.parent != parent_scope or not child.exported or child.kind not in {"function", "method"}:
            continue
        start = child.line or 1
        raw_end = child.end_line or child.line or start
        end = min(raw_end, start + MAX_BODY_SAMPLE_LINES - 1)
        ranges.append(
            _bounded_range(
                start,
                end,
                line_count,
                context_lines=0,
                reason="child_body_sample",
                symbol=child.scope or child.name,
            )
        )
        if len(ranges) >= limit:
            break
    return ranges


def _matching_symbols(symbols: list[SourceSymbol], requested_symbols: list[str]) -> list[SourceSymbol]:
    if not requested_symbols:
        return []
    needles = [symbol.lower() for symbol in requested_symbols if symbol.strip()]
    matches: list[SourceSymbol] = []
    for symbol in symbols:
        haystack = " ".join([symbol.name, symbol.scope, symbol.signature]).lower()
        if any(needle in haystack for needle in needles):
            matches.append(symbol)
    return matches


def _bounded_range(
    start: int,
    end: int,
    line_count: int,
    *,
    context_lines: int,
    reason: str,
    symbol: str = "",
) -> ProbeRange:
    return ProbeRange(
        start=max(1, start - context_lines),
        end=min(max(start, end + context_lines), max(1, line_count)),
        reason=reason,
        symbol=symbol,
    )


def _merge_ranges(ranges: list[ProbeRange]) -> list[ProbeRange]:
    merged: list[ProbeRange] = []
    for item in sorted(ranges, key=lambda range_item: (range_item.start, range_item.end)):
        if merged and _ranges_can_merge(merged[-1], item):
            previous = merged[-1]
            reason = previous.reason if previous.reason == item.reason else f"{previous.reason}+{item.reason}"
            symbol = previous.symbol or item.symbol
            merged[-1] = ProbeRange(previous.start, max(previous.end, item.end), reason, symbol)
            continue
        merged.append(item)
    return merged


def _ranges_can_merge(previous: ProbeRange, item: ProbeRange) -> bool:
    if item.start > previous.end + 1:
        return False
    if previous.symbol or item.symbol:
        return previous.symbol == item.symbol and previous.reason == item.reason
    return previous.reason == item.reason


def _render_ranges(path: Path, workspace_root: Path, content: str, ranges: list[ProbeRange]) -> str:
    relative = _relative(path, workspace_root)
    lines = content.splitlines()
    rendered = [f"Source probe for {relative}:"]
    for item in ranges:
        label = f"{item.reason} {item.symbol}".strip()
        rendered.append(f"\n[{item.start}-{item.end}] {label}")
        for line_number in range(item.start, item.end + 1):
            if 1 <= line_number <= len(lines):
                rendered.append(f"{line_number}: {lines[line_number - 1]}")
    if len(rendered) == 1:
        rendered.append("- no symbols or imports found")
    return "\n".join(rendered)


def _observation(
    *,
    path: Path,
    workspace_root: Path,
    analysis: SourceFileAnalysis,
    ranges: list[ProbeRange],
    include_edges: bool,
    truncated: bool,
    wide_symbols: list[dict[str, object]],
) -> dict[str, object]:
    symbols = [symbol.scope or symbol.name for symbol in analysis.symbols if symbol.exported][:12]
    edges: list[dict[str, object]] = []
    if include_edges:
        edges = enriched_outgoing_edges(
            analysis,
            current_file=path,
            workspace_root=workspace_root,
        )
    return {
        "kind": "source_probe",
        "target": _relative(path, workspace_root),
        "summary": f"Probed {Path(path).name} with {len(ranges)} bounded range(s)",
        "risk": "low",
        "observed_symbols": symbols,
        "line_ranges": [range_item.__dict__ for range_item in ranges],
        "wide_symbols": wide_symbols,
        "outgoing_edges": edges[:16],
        "truncated": truncated,
        "backend": analysis.backend,
    }


def _relative(path: Path, root: Path) -> str:
    try:
        return path.expanduser().resolve().relative_to(root.expanduser().resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()

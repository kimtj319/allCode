"""Aider-style bounded source overview tool."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.memory.repo_map import RepoMapBuilder
from allCode.memory.schema import RepoMapEntry
from allCode.tools.base import ToolContext, ToolDefinition
from allCode.tools.builtin.file_common import resolve_under_root
from allCode.tools.builtin.source_overview_metadata import (
    package_representative_reads,
    representative_read_limit,
    suggested_read_limit,
)
from allCode.tools.builtin.source_ranking import representative_reads_with_metadata
from allCode.workspace.indexer import DEFAULT_IGNORE_DIRS, SOURCE_EXTENSIONS, WorkspaceIndex, WorkspaceIndexer
from allCode.workspace.roots import WorkspaceRoots

ARCHITECTURE_FILE_STEMS = {
    "__init__",
    "__main__",
    "main",
    "cli",
    "app",
    "runtime",
    "loop",
    "runner",
    "router",
    "workflow",
    "registry",
    "executor",
    "manager",
    "service",
    "client",
    "parser",
    "schema",
    "models",
    "events",
    "indexer",
    "store",
}


class SourceOverviewTool:
    definition = ToolDefinition(
        name="source_overview",
        description=(
            "Summarize a source tree using file metadata and symbol signatures without dumping file bodies."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "focus": {
                    "type": "string",
                    "enum": ["package_roles", "entrypoints", "symbols", "tests", "recent_targets"],
                },
                "max_files": {"type": "integer"},
                "max_symbols": {"type": "integer"},
                "max_depth": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        read_only=True,
        group="search",
        aliases=["repo_overview"],
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        try:
            workspace_root = Path(context.workspace.root).expanduser().resolve()
            target = resolve_under_root(workspace_root, str(call.arguments.get("path", ".")))
            if not target.exists():
                return ToolResult(call_id=call.id, name=call.name, ok=False, error=f"path does not exist: {target}", error_type="not_found")
            max_files = min(max(1, int(call.arguments.get("max_files", 80))), 300)
            max_symbols = min(max(1, int(call.arguments.get("max_symbols", 120))), 500)
            max_depth = min(max(1, int(call.arguments.get("max_depth", 3))), 5)
            focus = str(call.arguments.get("focus", "package_roles"))

            index = _target_index(target=target, workspace_root=workspace_root, max_files=max_files)
            filtered = _filter_index(index, target=target, limit=max_files)
            entries = RepoMapBuilder().build_entries(filtered)
            groups = _group_entries(entries, max_depth=max_depth, max_symbols=max_symbols)
            representative_limit = representative_read_limit(groups=groups)
            representative_reads, representative_reasons, representative_scores = representative_reads_with_metadata(
                entries,
                groups=groups,
                focus=focus,
                limit=representative_limit,
            )
            analysis_backends = _analysis_backends(entries)
            semantic_edge_count = _semantic_edge_count(entries)
            suggested_reads = representative_reads[
                : suggested_read_limit(groups=groups, representative_count=len(representative_reads))
            ]
            package_representatives = package_representative_reads(
                groups=groups,
                representative_reads=representative_reads,
            )
            total_target_files = _count_source_files(target)
            truncated = index.truncated or len(filtered.files) < total_target_files
            coverage = _coverage(
                summarized_files=len(filtered.files),
                total_source_files=total_target_files,
                package_count=len(groups),
                truncated=truncated,
            )
            package_roles = _package_roles(groups)
            role_evidence = _role_evidence(groups)
            content = _render_overview(
                target=target,
                workspace_root=workspace_root,
                groups=groups,
                suggested_reads=suggested_reads,
                file_count=len(filtered.files),
                symbol_count=sum(len(entry.definitions) for entry in entries),
                truncated=truncated,
            )
            overview_paths = [group["path"] for group in groups]
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=True,
                content=content,
                metadata={
                    "focus": focus,
                    "target": _relative(target, workspace_root),
                    "overview_paths": overview_paths,
                    "source_overview_paths": overview_paths,
                    "source_overview_summaries": [str(group["summary"]) for group in groups],
                    "suggested_reads": suggested_reads,
                    "representative_reads": representative_reads,
                    "package_representative_reads": package_representatives,
                    "representative_reasons": representative_reasons,
                    "representative_scores": representative_scores,
                    "package_roles": package_roles,
                    "coverage": coverage,
                    "role_evidence": role_evidence,
                    "analysis_backends": analysis_backends,
                    "semantic_edge_count": semantic_edge_count,
                    "lsp_available": any(bool(entry.analysis_quality.get("lsp_available")) for entry in entries),
                    "file_count": len(filtered.files),
                    "symbol_count": sum(len(entry.definitions) for entry in entries),
                    "truncated": truncated,
                    "omitted_files": max(0, total_target_files - len(filtered.files)),
                    "observation": {
                        "kind": "source_overview",
                        "target": str(target),
                        "summary": f"Summarized {len(filtered.files)} file(s) under {_relative(target, workspace_root)}",
                        "risk": "low",
                    },
                },
            )
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)


def _filter_index(index: WorkspaceIndex, *, target: Path, limit: int) -> WorkspaceIndex:
    records = _records_under(index, target)
    selected = _select_balanced_records(records, limit=limit)
    return WorkspaceIndex(files=selected, skipped=index.skipped, truncated=index.truncated or len(records) > limit)


def _target_index(*, target: Path, workspace_root: Path, max_files: int) -> WorkspaceIndex:
    scan_root = target if target.is_dir() else target.parent
    scan_cap = min(2_000, max(max_files * 5, max_files + 200))
    raw_index = WorkspaceIndexer(max_files=scan_cap).build(WorkspaceRoots.from_root(scan_root))
    prefix = _relative(scan_root, workspace_root)
    records = []
    for record in raw_index.files:
        relative = record.relative_path
        if prefix and prefix != ".":
            relative = f"{prefix}/{relative}" if relative != "." else prefix
        records.append(record.model_copy(update={"root": str(workspace_root), "relative_path": relative}))
    return WorkspaceIndex(files=records, skipped=raw_index.skipped, truncated=raw_index.truncated)


def _records_under(index: WorkspaceIndex, target: Path) -> list:
    resolved_target = target.expanduser().resolve()
    records = []
    for record in index.files:
        try:
            path = Path(record.path).expanduser().resolve()
        except OSError:
            continue
        if path == resolved_target or resolved_target in path.parents:
            records.append(record)
    return records


def _select_balanced_records(records: list, *, limit: int) -> list:
    if limit <= 0:
        return []
    ordered = sorted(records, key=lambda record: record.relative_path)
    source_records = [record for record in ordered if Path(record.path).suffix.lower() in SOURCE_EXTENSIONS]
    other_records = [record for record in ordered if record not in source_records]
    selected = _round_robin_by_group(source_records, limit=limit)
    if len(selected) < limit:
        selected_paths = {record.relative_path for record in selected}
        for record in [*source_records, *other_records]:
            if record.relative_path in selected_paths:
                continue
            selected.append(record)
            selected_paths.add(record.relative_path)
            if len(selected) >= limit:
                break
    return selected[:limit]


def _round_robin_by_group(records: list, *, limit: int) -> list:
    grouped: dict[str, list] = defaultdict(list)
    for record in records:
        grouped[_record_group(record.relative_path)].append(record)
    for bucket in grouped.values():
        bucket.sort(key=lambda record: _record_priority(record.relative_path))
    selected: list = []
    seen: set[str] = set()
    group_keys = sorted(grouped)
    while len(selected) < limit and group_keys:
        progressed = False
        for key in group_keys:
            bucket = grouped[key]
            if not bucket:
                continue
            record = bucket.pop(0)
            if record.relative_path in seen:
                continue
            selected.append(record)
            seen.add(record.relative_path)
            progressed = True
            if len(selected) >= limit:
                break
        if not progressed:
            break
    return selected


def _record_group(relative_path: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) >= 4:
        return "/".join(parts[:3])
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0] if parts else "."


def _record_priority(relative_path: str) -> tuple[int, int, str]:
    name = Path(relative_path).name
    stem = Path(relative_path).stem.lower()
    entrypoint = 0 if name in {"__main__.py", "main.py", "cli.py", "app.py", "runtime.py"} else 1
    architecture = 0 if stem in ARCHITECTURE_FILE_STEMS else 1
    package_init = 1 if name == "__init__.py" else 0
    private = 1 if name.startswith("_") else 0
    return (entrypoint, architecture, package_init, private, relative_path)


def _count_source_files(target: Path) -> int:
    if target.is_file():
        return int(target.suffix.lower() in SOURCE_EXTENSIONS)
    count = 0
    for path in target.rglob("*"):
        if any(part in DEFAULT_IGNORE_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS:
            count += 1
    return count


def _group_entries(entries: list[RepoMapEntry], *, max_depth: int, max_symbols: int) -> list[dict[str, object]]:
    grouped: dict[str, list[RepoMapEntry]] = defaultdict(list)
    for entry in entries:
        parts = Path(entry.path).parts
        depth = min(max_depth, max(1, len(parts) - 1))
        key = "/".join(parts[:depth]) if parts else entry.path
        grouped[key].append(entry)
    groups: list[dict[str, object]] = []
    sorted_groups = sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0]))[:24]
    per_group_symbol_cap = max(3, min(12, max_symbols // max(1, len(sorted_groups))))
    for key, items in sorted_groups:
        definitions: list[str] = []
        imports: list[str] = []
        languages = sorted({entry.language or "text" for entry in items})
        for entry in items:
            for definition in entry.definitions:
                if len(definitions) >= per_group_symbol_cap:
                    break
                definitions.append(f"{entry.path}: {definition}")
            for imported in entry.imports[:3]:
                if imported and imported not in imports:
                    imports.append(imported)
        summary = f"{len(items)} file(s), languages: {', '.join(languages[:4])}"
        if definitions:
            summary += f", symbols: {len(definitions)}"
        groups.append(
            {
                "path": key,
                "file_count": len(items),
                "languages": languages,
                "definitions": definitions[:12],
                "imports": imports[:8],
                "summary": summary,
            }
        )
    return groups


def _coverage(*, summarized_files: int, total_source_files: int, package_count: int, truncated: bool) -> dict[str, object]:
    ratio = 1.0 if total_source_files <= 0 else min(1.0, summarized_files / total_source_files)
    return {
        "summarized_files": summarized_files,
        "total_source_files": total_source_files,
        "package_count": package_count,
        "coverage_ratio": round(ratio, 4),
        "truncated": truncated,
    }


def _package_roles(groups: list[dict[str, object]]) -> list[dict[str, object]]:
    roles: list[dict[str, object]] = []
    for group in groups[:12]:
        definitions = group.get("definitions") if isinstance(group.get("definitions"), list) else []
        imports = group.get("imports") if isinstance(group.get("imports"), list) else []
        path = str(group.get("path") or "")
        file_count = int(group.get("file_count") or 0)
        role, confidence = _infer_role(path, definitions, imports, file_count=file_count)
        roles.append({"path": path, "role": role, "confidence": confidence})
    return roles


def _infer_role(path: str, definitions: list, imports: list, *, file_count: int) -> tuple[str, float]:
    path_tokens = _path_tokens(path)
    filenames = _definition_filenames(definitions)
    symbol_names = " ".join(_definition_symbol_name(item).lower() for item in definitions[:12])
    if path_tokens & {"tests", "test", "spec", "specs"} or any(_looks_test_filename(name) for name in filenames):
        return "test or verification support", 0.7
    keyword_role = _role_from_path_keywords(path_tokens)
    if keyword_role is not None:
        return keyword_role
    if any(name in filenames for name in ("main.py", "__main__.py", "cli.py")):
        return "entrypoint or command/runtime wiring", 0.75
    if any(token in symbol_names for token in ("command", "runtime", "runner", "application")):
        return "runtime orchestration or command wiring", 0.7
    if definitions and imports:
        return "public code surface coordinating imported dependencies", 0.68
    if definitions:
        return "source module defining public classes or functions", 0.62
    if imports:
        return "integration or dependency wiring module", 0.58
    if file_count > 1:
        return "source package group", 0.5
    return "source file group", 0.45


def _path_tokens(path: str) -> set[str]:
    tokens: set[str] = set()
    for part in Path(path).parts:
        tokens.update(token for token in re.split(r"[^A-Za-z0-9]+", part.lower()) if token)
    return tokens


def _definition_filenames(definitions: list) -> set[str]:
    filenames: set[str] = set()
    for item in definitions:
        text = str(item)
        if ":" not in text:
            continue
        filenames.add(Path(text.split(":", 1)[0]).name.lower())
    return filenames


def _definition_symbol_name(definition: object) -> str:
    text = str(definition)
    tail = text.split(":", 1)[-1].strip()
    for marker in ("async def ", "def ", "class ", "function ", "const ", "let ", "var "):
        if marker in tail:
            tail = tail.split(marker, 1)[1]
            break
    return tail.split("(", 1)[0].split("=", 1)[0].strip()


def _looks_test_filename(filename: str) -> bool:
    return filename.startswith("test_") or filename.endswith("_test.py") or filename.endswith(".spec.ts")


def _role_from_path_keywords(tokens: set[str]) -> tuple[str, float] | None:
    if "agent" in tokens or "agents" in tokens:
        return "agent loop, routing, planning, and completion orchestration", 0.82
    if "tool" in tokens or "tools" in tokens:
        return "tool registry, policy, approval, and builtin tool execution", 0.82
    if "memory" in tokens or "context" in tokens:
        return "workspace context, session memory, and repo map state", 0.8
    if "llm" in tokens or "model" in tokens or "models" in tokens:
        return "provider-neutral model adapter, streaming, and response parsing", 0.8
    if "core" in tokens or "common" in tokens:
        return "shared provider-neutral contracts, events, errors, and results", 0.78
    if "config" in tokens or "settings" in tokens:
        return "configuration schema, defaults, and environment loading", 0.78
    if "tui" in tokens or "ui" in tokens or "terminal" in tokens:
        return "terminal UI rendering, input handling, and status presentation", 0.78
    if "workspace" in tokens or "project" in tokens:
        return "workspace roots, indexing, path policy, and source intelligence", 0.78
    if "generation" in tokens or "workflow" in tokens:
        return "project generation workflow and language strategies", 0.76
    if "telemetry" in tokens or "logging" in tokens:
        return "session logging, runtime metrics, and diagnostics", 0.76
    return None


def _role_evidence(groups: list[dict[str, object]]) -> list[str]:
    evidence: list[str] = []
    for group in groups[:12]:
        path = str(group.get("path") or "")
        definitions = group.get("definitions") if isinstance(group.get("definitions"), list) else []
        imports = group.get("imports") if isinstance(group.get("imports"), list) else []
        if definitions:
            evidence.append(f"{path}: definitions: {', '.join(str(item) for item in definitions[:3])}")
        elif imports:
            evidence.append(f"{path}: imports: {', '.join(str(item) for item in imports[:3])}")
        elif path:
            evidence.append(f"{path}: file_count={group.get('file_count')}")
    return evidence[:12]


def _analysis_backends(entries: list[RepoMapEntry]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        backend = entry.analysis_backend or "unknown"
        counts[backend] = counts.get(backend, 0) + 1
    return counts


def _semantic_edge_count(entries: list[RepoMapEntry]) -> int:
    total = 0
    for entry in entries:
        total += len(entry.references_detail)
    return total


def _render_overview(
    *,
    target: Path,
    workspace_root: Path,
    groups: list[dict[str, object]],
    suggested_reads: list[str],
    file_count: int,
    symbol_count: int,
    truncated: bool,
) -> str:
    relative_target = _relative(target, workspace_root)
    lines = [
        f"Source overview for {relative_target}:",
        f"- files summarized: {file_count}",
        f"- symbols summarized: {symbol_count}",
        f"- truncated: {str(truncated).lower()}",
        "- top modules:",
    ]
    for group in groups[:12]:
        lines.append(f"  - {group['path']}: {group['summary']}")
        definitions = group.get("definitions")
        if isinstance(definitions, list) and definitions:
            for definition in definitions[:3]:
                lines.append(f"    - {definition}")
    if suggested_reads:
        lines.append("- suggested reads:")
        lines.extend(f"  - {path}" for path in suggested_reads[:12])
    return "\n".join(lines)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.expanduser().resolve().relative_to(root.expanduser().resolve()).as_posix() or "."
    except (OSError, ValueError):
        return path.as_posix()

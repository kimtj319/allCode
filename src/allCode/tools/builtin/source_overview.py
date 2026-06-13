"""Aider-style bounded source overview tool."""

from __future__ import annotations

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
from allCode.tools.builtin.source_overview_roles import (
    ARCHITECTURE_FILE_STEMS,
    package_roles,
    role_evidence,
)
from allCode.tools.builtin.source_query_relevance import path_query_relevance_score, query_relevance_tokens
from allCode.tools.builtin.source_ranking import representative_reads_with_metadata
from allCode.workspace.indexer import CODE_EXTENSIONS, DEFAULT_IGNORE_DIRS, SOURCE_EXTENSIONS, WorkspaceIndex, WorkspaceIndexer
from allCode.workspace.roots import WorkspaceRoots

# Runtime entrypoints that anchor the top of the execution spine.
_ENTRYPOINT_NAMES = {"__main__.py", "main.py", "cli.py", "runtime.py"}


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
                "query": {
                    "type": "string",
                    "description": "Optional user request summary used only to rank representative source files.",
                },
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
            query = _combined_query(context.user_prompt, str(call.arguments.get("query") or ""))

            index = _target_index(target=target, workspace_root=workspace_root, max_files=max_files)
            filtered = _filter_index(index, target=target, limit=max_files, query=query)
            entries = RepoMapBuilder().build_entries(filtered)
            groups = _group_entries(entries, max_depth=max_depth, max_symbols=max_symbols)
            representative_limit = representative_read_limit(groups=groups)
            representative_reads, representative_reasons, representative_scores = representative_reads_with_metadata(
                entries,
                groups=groups,
                focus=focus,
                limit=representative_limit,
                query=query,
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
            inferred_roles = package_roles(groups)
            role_evidence_items = role_evidence(groups)
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
                    "package_roles": inferred_roles,
                    "coverage": coverage,
                    "role_evidence": role_evidence_items,
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


def _filter_index(index: WorkspaceIndex, *, target: Path, limit: int, query: str = "") -> WorkspaceIndex:
    records = _records_under(index, target)
    selected = _select_balanced_records(records, limit=limit, query=query)
    return WorkspaceIndex(files=selected, skipped=index.skipped, truncated=index.truncated or len(records) > limit)


def _combined_query(user_prompt: str, tool_query: str) -> str:
    parts = [part.strip() for part in (user_prompt, tool_query) if part and part.strip()]
    return "\n".join(dict.fromkeys(parts))


def _gitignore_dirs(workspace_root: Path) -> set[str]:
    """Top-level directory names the repo gitignores (build output, generated
    trees, vendored deps, and—per project choice—tests/docs). Architecture
    overviews should center on tracked source, so these are skipped for the
    overview scan only (the global index is unaffected)."""

    names: set[str] = set()
    try:
        text = (workspace_root / ".gitignore").read_text(encoding="utf-8")
    except OSError:
        return names
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        candidate = line.rstrip("/")
        # Only simple directory-name patterns; ignore globs and nested paths.
        if not candidate or "/" in candidate or "*" in candidate or "?" in candidate:
            continue
        names.add(candidate)
    return names


def _target_index(*, target: Path, workspace_root: Path, max_files: int) -> WorkspaceIndex:
    scan_root = target if target.is_dir() else target.parent
    scan_cap = min(2_000, max(max_files * 5, max_files + 200))
    ignore_dirs = DEFAULT_IGNORE_DIRS | _gitignore_dirs(workspace_root)
    raw_index = WorkspaceIndexer(max_files=scan_cap, ignore_dirs=ignore_dirs).build(WorkspaceRoots.from_root(scan_root))
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


def _select_balanced_records(records: list, *, limit: int, query: str = "") -> list:
    if limit <= 0:
        return []
    query_tokens = query_relevance_tokens(query)
    ordered = sorted(records, key=lambda record: record.relative_path)
    code_records: list = []
    doc_records: list = []
    other_records: list = []
    for record in ordered:
        suffix = Path(record.path).suffix.lower()
        if suffix in CODE_EXTENSIONS:
            code_records.append(record)
        elif suffix in SOURCE_EXTENSIONS:
            doc_records.append(record)
        else:
            other_records.append(record)
    # Always surface the runtime entrypoints first. They live in a small top-level
    # package that the size-capped round-robin can otherwise drop, which leaves the
    # analysis without the main -> runtime -> loop spine.
    selected: list = []
    selected_paths: set[str] = set()
    for record in code_records:
        if Path(record.path).name in _ENTRYPOINT_NAMES and record.relative_path not in selected_paths:
            selected.append(record)
            selected_paths.add(record.relative_path)
            if len(selected) >= limit:
                return selected[:limit]
    # Architecture overviews should center on real code: fill the budget from the
    # largest code packages first, then top up with docs/config/data only if room
    # remains. This keeps generated/scratch trees from diluting the core source.
    remaining = [record for record in code_records if record.relative_path not in selected_paths]
    for record in _round_robin_by_group(remaining, limit=limit - len(selected), query_tokens=query_tokens):
        if record.relative_path not in selected_paths:
            selected.append(record)
            selected_paths.add(record.relative_path)
    if len(selected) < limit:
        doc_fill = _round_robin_by_group(doc_records, limit=limit - len(selected), query_tokens=query_tokens)
        for record in [*doc_fill, *other_records]:
            if record.relative_path in selected_paths:
                continue
            selected.append(record)
            selected_paths.add(record.relative_path)
            if len(selected) >= limit:
                break
    return selected[:limit]


def _round_robin_by_group(records: list, *, limit: int, query_tokens: set[str] | None = None) -> list:
    query_tokens = query_tokens or set()
    grouped: dict[str, list] = defaultdict(list)
    for record in records:
        grouped[_record_group(record.relative_path)].append(record)
    for bucket in grouped.values():
        bucket.sort(key=lambda record: _record_priority(record.relative_path, query_tokens=query_tokens))
    selected: list = []
    seen: set[str] = set()
    # Restrict the round-robin to the densest groups so a project with many small
    # scattered directories (generated outputs, fixtures) cannot crowd out the few
    # large packages that actually define the architecture. The cap scales with the
    # budget so each kept group still contributes several files.
    max_groups = max(8, limit // 3)
    group_keys = sorted(grouped, key=lambda key: (-len(grouped[key]), key))[:max_groups]
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


def _record_priority(relative_path: str, *, query_tokens: set[str]) -> tuple[int, float, int, int, int, str]:
    name = Path(relative_path).name
    stem = Path(relative_path).stem.lower()
    entrypoint = 0 if name in {"__main__.py", "main.py", "cli.py", "app.py", "runtime.py"} else 1
    query_relevance = -path_query_relevance_score(relative_path, query_tokens)
    architecture = 0 if stem in ARCHITECTURE_FILE_STEMS else 1
    package_init = 1 if name == "__init__.py" else 0
    private = 1 if name.startswith("_") else 0
    return (entrypoint, query_relevance, architecture, package_init, private, relative_path)


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

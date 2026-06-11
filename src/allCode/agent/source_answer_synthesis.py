"""Synthesis helpers for source-inspection observations."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from allCode.agent.language import ResponseLanguage
from allCode.agent.inspect_targets import explicit_target_paths, target_observed
from allCode.agent.source_analysis_rendering import (
    render_compact_source_analysis_brief,
    render_source_analysis_brief,
    source_answer_needs_compact_brief,
    source_analysis_final_answer_instruction,
)
from allCode.agent.source_analysis_types import (
    PackageRole,
    RepresentativeFile,
    SourceAnalysisBrief,
    SourceEdge,
)
from allCode.agent.source_responsibility_graph import build_source_responsibility_graph
from allCode.agent.source_inspection_budget import required_representative_probe_count
from allCode.core.models import ToolResult
from allCode.core.result import CompletionEvidence

__all__ = [
    "PackageRole",
    "RepresentativeFile",
    "SourceAnalysisBrief",
    "SourceEdge",
    "build_source_analysis_brief",
    "probe_evidence_lines",
    "render_compact_source_analysis_brief",
    "render_source_analysis_brief",
    "source_answer_needs_compact_brief",
    "source_analysis_final_answer_instruction",
]


def build_source_analysis_brief(
    tool_results: Sequence[ToolResult],
    *,
    evidence: CompletionEvidence,
    user_prompt: str = "",
) -> SourceAnalysisBrief:
    observed_paths = _observed_paths(tool_results, evidence=evidence)
    representative_files = _representative_files(tool_results)
    package_roles = _package_roles(tool_results, evidence=evidence)
    edges = _source_edges(tool_results)
    responsibility_graph = build_source_responsibility_graph(
        tool_results,
        representative_files=representative_files,
        edges=edges,
    )
    entrypoints = _entrypoints(representative_files)
    inferred_flows = _inferred_flows(edges, representative_files)
    explicit_targets = explicit_target_paths(user_prompt) if user_prompt else []
    observed_target_paths = set([*observed_paths, *evidence.source_overview_targets])
    unobserved = [target for target in explicit_targets if not target_observed(target, observed_target_paths)]
    unobserved.extend(_unobserved_representative_candidates(evidence))
    confidence_notes: list[str] = []
    if evidence.source_overview_truncated:
        confidence_notes.append("source overview was truncated")
    coverage = evidence.source_analysis_coverage or {}
    if coverage.get("coverage_ratio") is not None:
        confidence_notes.append(f"coverage ratio {coverage.get('coverage_ratio')}")
    return SourceAnalysisBrief(
        requested_scope=", ".join(explicit_targets) if explicit_targets else user_prompt[:160],
        observed_paths=observed_paths[:40],
        representative_files=representative_files[:12],
        package_roles=package_roles[:16],
        entrypoints=entrypoints[:8],
        cross_module_edges=edges[:20],
        inferred_flows=inferred_flows[:12],
        responsibility_graph=responsibility_graph.model_dump(mode="json"),
        unobserved_scopes=unobserved[:12],
        confidence_notes=confidence_notes[:6],
    )


def _unobserved_representative_candidates(evidence: CompletionEvidence) -> list[str]:
    observed = {_clean_path(path) for path in [*evidence.inspected_paths, *evidence.representative_read_paths]}
    candidates = [_clean_path(path) for path in evidence.source_representative_candidates if _clean_path(path)]
    required_missing = _required_unobserved_representative_count(
        evidence,
        candidate_count=len(candidates),
        observed_count=sum(1 for path in candidates if path in observed),
    )
    if required_missing <= 0:
        return []
    ranked = sorted(
        candidates,
        key=lambda path: evidence.source_representative_scores.get(path, 0.0),
        reverse=True,
    )
    missing: list[str] = []
    for path in ranked:
        cleaned = _clean_path(path)
        if cleaned and cleaned not in observed and cleaned not in missing:
            missing.append(cleaned)
            if len(missing) >= required_missing:
                break
    return missing[:8]


def _required_unobserved_representative_count(
    evidence: CompletionEvidence,
    *,
    candidate_count: int,
    observed_count: int,
) -> int:
    required = required_representative_probe_count(evidence, candidate_count=candidate_count)
    return max(0, required - observed_count)


def probe_evidence_lines(
    tool_results: Sequence[ToolResult],
    *,
    language: ResponseLanguage,
) -> tuple[list[str], list[str], list[str]]:
    file_lines: list[str] = []
    symbol_lines: list[str] = []
    edge_lines: list[str] = []
    for result in tool_results:
        observation = result.metadata.get("observation")
        if not result.ok or not isinstance(observation, dict) or observation.get("kind") != "source_probe":
            continue
        target = _clean(str(observation.get("target") or result.metadata.get("file_path") or ""))
        if not target:
            continue
        ranges = _range_labels(observation.get("line_ranges"))
        backend = _clean(str(observation.get("backend") or result.metadata.get("backend") or ""))
        detail = []
        if ranges:
            detail.append("ranges " + ", ".join(ranges[:4]))
        if backend:
            detail.append(f"backend `{backend}`")
        if detail:
            file_lines.append(f"`{target}`: " + "; ".join(detail))
        symbols = [str(item) for item in observation.get("observed_symbols", []) if str(item).strip()]
        if symbols:
            symbol_lines.append(f"`{target}`: " + ", ".join(f"`{symbol}`" for symbol in symbols[:8]))
        edges = _edge_labels(observation.get("outgoing_edges"))
        if edges:
            label = "import/reference" if language == "en" else "가져오기/참조"
            edge_lines.append(f"`{target}` {label}: " + ", ".join(edges[:8]))
    return file_lines[:10], symbol_lines[:10], edge_lines[:10]


def _observed_paths(tool_results: Sequence[ToolResult], *, evidence: CompletionEvidence) -> list[str]:
    paths: list[str] = []
    for path in [
        *evidence.source_overview_targets,
        *evidence.source_overview_paths,
        *evidence.inspected_paths,
        *evidence.representative_read_paths,
        *evidence.source_representative_candidates,
        *evidence.search_candidate_paths,
    ]:
        _append(paths, _clean_path(path))
    for result in tool_results:
        observation = result.metadata.get("observation")
        if isinstance(observation, dict):
            _append(paths, _clean_path(str(observation.get("target") or "")))
        for key in ("file_path", "path"):
            _append(paths, _clean_path(str(result.metadata.get(key) or "")))
        for key in ("representative_reads", "suggested_reads"):
            for value in result.metadata.get(key, []):
                if isinstance(value, str):
                    _append(paths, _clean_path(value))
    return paths


def _representative_files(tool_results: Sequence[ToolResult]) -> list[RepresentativeFile]:
    files: list[RepresentativeFile] = []
    seen: set[str] = set()
    for result in tool_results:
        observation = result.metadata.get("observation")
        if isinstance(observation, dict) and observation.get("kind") == "source_probe":
            path = _clean_path(str(observation.get("target") or result.metadata.get("file_path") or ""))
            if path and path not in seen:
                seen.add(path)
                files.append(
                    RepresentativeFile(
                        path=path,
                        evidence="source_probe",
                        symbols=[str(item) for item in observation.get("observed_symbols", []) if str(item).strip()][:10],
                        ranges=_prioritized_range_labels(_range_labels(observation.get("line_ranges")))[:6],
                        wiring=_edge_labels(observation.get("outgoing_edges"))[:8],
                        wide_symbols=_wide_symbol_labels(observation.get("wide_symbols"))[:6],
                    )
                )
            continue
        if result.name == "read_file" or result.metadata.get("tool_name") == "read_file":
            path = _clean_path(str(result.metadata.get("file_path") or ""))
            if path and path not in seen:
                seen.add(path)
                files.append(
                    RepresentativeFile(
                        path=path,
                        evidence="read_file",
                        ranges=_read_file_range_labels(result.metadata.get("returned_range"))[:2],
                    )
                )
    return files


def _package_roles(tool_results: Sequence[ToolResult], *, evidence: CompletionEvidence) -> list[PackageRole]:
    roles: list[PackageRole] = []
    seen: set[str] = set()
    for role in [*evidence.source_package_roles, *_metadata_roles(tool_results)]:
        if not isinstance(role, dict):
            continue
        path = _clean_path(str(role.get("path") or ""))
        label = str(role.get("role") or "").strip()
        if not path or not label:
            continue
        key = f"{path}:{label}"
        if key in seen:
            continue
        seen.add(key)
        roles.append(PackageRole(path=path, role=label, evidence="package_role metadata"))
    if roles:
        return roles
    for path in evidence.source_overview_paths[:12]:
        scope = _scope(_clean_path(path))
        if scope and scope not in seen:
            seen.add(scope)
            roles.append(PackageRole(path=scope, role="observed source area", evidence="source overview"))
    return roles


def _metadata_roles(tool_results: Sequence[ToolResult]) -> list[dict[str, object]]:
    roles: list[dict[str, object]] = []
    for result in tool_results:
        for role in result.metadata.get("package_roles", []):
            if isinstance(role, dict):
                roles.append(role)
    return roles


def _source_edges(tool_results: Sequence[ToolResult]) -> list[SourceEdge]:
    edges: list[SourceEdge] = []
    seen: set[str] = set()
    for result in tool_results:
        observation = result.metadata.get("observation")
        if not isinstance(observation, dict) or observation.get("kind") != "source_probe":
            continue
        source = _clean_path(str(observation.get("target") or result.metadata.get("file_path") or ""))
        for item in observation.get("outgoing_edges", []):
            if not isinstance(item, dict):
                continue
            raw_target = str(item.get("target") or item.get("symbol") or "").strip()
            target = str(item.get("resolved_target") or raw_target).strip()
            kind = str(item.get("kind") or "reference").strip() or "reference"
            line = item.get("line")
            if isinstance(line, int) and line > 0:
                kind = f"{kind}@L{line}"
            key = f"{source}:{kind}:{target}"
            if source and target and key not in seen:
                seen.add(key)
                edges.append(SourceEdge(source=source, target=target, kind=kind))
    return sorted(edges, key=_source_edge_priority)


def _source_edge_priority(edge: SourceEdge) -> tuple[int, str, str]:
    target = str(edge.target or "")
    if target.startswith("src/"):
        return (0, edge.source, target)
    if "/" in target and target.endswith((".py", ".js", ".ts", ".go", ".rs", ".java")):
        return (1, edge.source, target)
    if "." in target and "/" not in target:
        return (2, edge.source, target)
    if ":" in target:
        return (4, edge.source, target)
    return (3, edge.source, target)


def _entrypoints(files: Sequence[RepresentativeFile]) -> list[str]:
    entries: list[str] = []
    for file in files:
        for symbol in file.symbols:
            lowered = symbol.lower()
            if lowered in {"main", "__main__"} or lowered.endswith(".main") or "cli" in lowered:
                _append(entries, f"{file.path}:{symbol}")
    return entries


def _inferred_flows(edges: Sequence[SourceEdge], files: Sequence[RepresentativeFile]) -> list[str]:
    flows: list[str] = []
    for edge in edges[:10]:
        flows.append(f"`{edge.source}`에서 `{edge.target}`를 {edge.kind}로 참조합니다.")
    if not flows:
        for file in files[:6]:
            if file.symbols:
                flows.append(f"`{file.path}`의 public symbol `{file.symbols[0]}`가 해당 영역의 주요 진입 단서입니다.")
    return flows


def _range_labels(value: object) -> list[str]:
    labels: list[str] = []
    if not isinstance(value, list):
        return labels
    for item in value:
        if not isinstance(item, dict):
            continue
        start = item.get("start")
        end = item.get("end")
        reason = _clean(str(item.get("reason") or "range"))
        symbol = _clean(str(item.get("symbol") or ""))
        if start and end:
            suffix = f":{symbol}" if symbol else ""
            labels.append(f"L{start}-L{end}({reason}{suffix})")
    return labels


def _prioritized_range_labels(labels: list[str]) -> list[str]:
    return sorted(labels, key=_range_label_priority)


def _range_label_priority(label: str) -> tuple[int, str]:
    lowered = label.lower()
    if "body_sample" in lowered:
        return (0, label)
    if "symbol" in lowered or "signature" in lowered:
        return (1, label)
    if "read_file" in lowered:
        return (2, label)
    if "imports" in lowered:
        return (3, label)
    return (4, label)


def _edge_labels(value: object) -> list[str]:
    labels: list[str] = []
    if not isinstance(value, list):
        return labels
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = _clean(str(item.get("kind") or "edge"))
        raw_target = _clean(str(item.get("target") or item.get("symbol") or ""))
        resolved_target = _clean_path(str(item.get("resolved_target") or ""))
        target = resolved_target or raw_target
        if target:
            label = f"{kind}:{raw_target}"
            if resolved_target:
                label = f"{label}->{resolved_target}"
            line = item.get("line")
            if isinstance(line, int) and line > 0:
                label = f"{label}@L{line}"
            if label not in labels:
                labels.append(label)
    return labels


def _wide_symbol_labels(value: object) -> list[str]:
    labels: list[str] = []
    if not isinstance(value, list):
        return labels
    for item in value:
        if not isinstance(item, dict):
            continue
        symbol = _clean(str(item.get("symbol") or ""))
        span = item.get("span_lines")
        kind = _clean(str(item.get("kind") or "symbol"))
        summary = _clean(str(item.get("summary") or "header/signatures only"))
        if symbol and isinstance(span, int) and span > 0:
            labels.append(f"{symbol}({kind}, {span} lines, {summary})")
        elif symbol:
            labels.append(f"{symbol}({kind}, {summary})")
    return labels


def _read_file_range_labels(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) != 2:
        return []
    start, end = value
    if not isinstance(start, int) or not isinstance(end, int) or start <= 0 or end <= 0:
        return []
    return [f"L{start}-L{end}(read_file)"]


def _clean(value: str) -> str:
    return value.strip().strip("`")


def _clean_path(path: str) -> str:
    value = path.strip().strip("`")
    if not value:
        return ""
    if value.startswith("/workspace/"):
        return value[len("/workspace/") :]
    parts = Path(value).parts
    for anchor in ("src", "tests", "test"):
        if anchor in parts:
            return "/".join(parts[parts.index(anchor) :])
    if Path(value).is_absolute() and len(parts) > 3:
        return "/".join(parts[-3:])
    return value


def _scope(path: str) -> str:
    parts = Path(path).parts
    if not parts:
        return ""
    if "." in parts[-1] and len(parts) > 1:
        return "/".join(parts[:-1])
    return "/".join(parts)


def _append(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)

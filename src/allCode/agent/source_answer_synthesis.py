"""Synthesis helpers for source-inspection observations."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from allCode.agent.language import ResponseLanguage
from allCode.agent.inspect_targets import explicit_target_paths, target_observed
from allCode.core.models import CoreModel
from allCode.core.models import ToolResult
from allCode.core.result import CompletionEvidence
from pydantic import Field


class RepresentativeFile(CoreModel):
    path: str
    evidence: str = ""
    symbols: list[str] = Field(default_factory=list)
    ranges: list[str] = Field(default_factory=list)
    wiring: list[str] = Field(default_factory=list)


class PackageRole(CoreModel):
    path: str
    role: str
    evidence: str = ""


class SourceEdge(CoreModel):
    source: str
    target: str
    kind: str = "reference"


class SourceAnalysisBrief(CoreModel):
    requested_scope: str = ""
    observed_paths: list[str] = Field(default_factory=list)
    representative_files: list[RepresentativeFile] = Field(default_factory=list)
    package_roles: list[PackageRole] = Field(default_factory=list)
    entrypoints: list[str] = Field(default_factory=list)
    cross_module_edges: list[SourceEdge] = Field(default_factory=list)
    inferred_flows: list[str] = Field(default_factory=list)
    unobserved_scopes: list[str] = Field(default_factory=list)
    confidence_notes: list[str] = Field(default_factory=list)


def source_analysis_final_answer_instruction(language: ResponseLanguage) -> str:
    if language == "en":
        return (
            "Write the final source-analysis answer now. Use only observed tool evidence and supplied context. "
            "Do not mutate files. Do not output raw tool JSON. Structure the answer with: checked scope, "
            "package/directory roles, key execution flow, module interactions, representative file evidence, "
            "and remaining limitations. Separate observed facts from inferred roles."
        )
    return (
        "이제 최종 소스 분석 답변을 작성하십시오. 관찰된 도구 근거와 제공된 컨텍스트만 사용하고 파일은 수정하지 마십시오. "
        "raw tool JSON을 출력하지 마십시오. 답변에는 확인한 범위, 디렉터리/패키지별 역할, 핵심 실행 흐름, "
        "모듈 간 연결, 대표 파일 근거, 남은 한계를 포함하십시오. 관찰한 사실과 추론한 역할을 분리하십시오."
    )


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
    entrypoints = _entrypoints(representative_files)
    inferred_flows = _inferred_flows(edges, representative_files)
    explicit_targets = explicit_target_paths(user_prompt) if user_prompt else []
    observed_target_paths = set([*observed_paths, *evidence.source_overview_targets])
    unobserved = [target for target in explicit_targets if not target_observed(target, observed_target_paths)]
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
        unobserved_scopes=unobserved[:12],
        confidence_notes=confidence_notes[:6],
    )


def render_source_analysis_brief(brief: SourceAnalysisBrief, *, language: ResponseLanguage) -> str:
    if language == "en":
        lines = ["Source analysis evidence brief:"]
        if brief.observed_paths:
            lines.extend(["", "Checked scope:", *[f"- `{path}`" for path in brief.observed_paths[:12]]])
        if brief.package_roles:
            lines.extend(["", "Package/directory roles:"])
            lines.extend(f"- `{role.path}`: {role.role} ({role.evidence or 'observed/inferred evidence'})" for role in brief.package_roles[:10])
        if brief.inferred_flows:
            lines.extend(["", "Key execution flow:", *[f"- {flow}" for flow in brief.inferred_flows[:8]]])
        if brief.cross_module_edges:
            lines.extend(["", "Module interactions:"])
            lines.extend(f"- `{edge.source}` --{edge.kind}--> `{edge.target}`" for edge in brief.cross_module_edges[:10])
        if brief.representative_files:
            lines.extend(["", "Representative file evidence:"])
            lines.extend(_representative_file_lines(brief.representative_files[:8]))
        if brief.unobserved_scopes or brief.confidence_notes:
            lines.append("")
            lines.append("Limitations:")
            lines.extend(f"- `{target}` was not observed." for target in brief.unobserved_scopes[:8])
            lines.extend(f"- {note}" for note in brief.confidence_notes[:6])
        return "\n".join(lines)

    lines = ["소스 분석 근거 brief:"]
    if brief.observed_paths:
        lines.extend(["", "확인한 범위:", *[f"- `{path}`" for path in brief.observed_paths[:12]]])
    if brief.package_roles:
        lines.extend(["", "디렉터리/패키지별 역할:"])
        lines.extend(f"- `{role.path}`: {role.role} ({role.evidence or '관찰/추론 근거'})" for role in brief.package_roles[:10])
    if brief.inferred_flows:
        lines.extend(["", "핵심 실행 흐름:", *[f"- {flow}" for flow in brief.inferred_flows[:8]]])
    if brief.cross_module_edges:
        lines.extend(["", "모듈 간 연결:"])
        lines.extend(f"- `{edge.source}` --{edge.kind}--> `{edge.target}`" for edge in brief.cross_module_edges[:10])
    if brief.representative_files:
        lines.extend(["", "대표 파일 근거:"])
        lines.extend(_representative_file_lines(brief.representative_files[:8]))
    if brief.unobserved_scopes or brief.confidence_notes:
        lines.append("")
        lines.append("남은 한계:")
        lines.extend(f"- `{target}`는 직접 관찰하지 못했습니다." for target in brief.unobserved_scopes[:8])
        lines.extend(f"- {note}" for note in brief.confidence_notes[:6])
    return "\n".join(lines)


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
                        ranges=_range_labels(observation.get("line_ranges"))[:6],
                        wiring=_edge_labels(observation.get("outgoing_edges"))[:8],
                    )
                )
            continue
        if result.name == "read_file" or result.metadata.get("tool_name") == "read_file":
            path = _clean_path(str(result.metadata.get("file_path") or ""))
            if path and path not in seen:
                seen.add(path)
                files.append(RepresentativeFile(path=path, evidence="read_file"))
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
            target = str(item.get("target") or item.get("symbol") or "").strip()
            kind = str(item.get("kind") or "reference").strip() or "reference"
            key = f"{source}:{kind}:{target}"
            if source and target and key not in seen:
                seen.add(key)
                edges.append(SourceEdge(source=source, target=target, kind=kind))
    return edges


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


def _representative_file_lines(files: Sequence[RepresentativeFile]) -> list[str]:
    lines: list[str] = []
    for file in files:
        details: list[str] = [file.evidence] if file.evidence else []
        if file.symbols:
            details.append("symbols " + ", ".join(f"`{symbol}`" for symbol in file.symbols[:5]))
        if file.ranges:
            details.append("ranges " + ", ".join(file.ranges[:4]))
        if file.wiring:
            details.append("wiring " + ", ".join(file.wiring[:4]))
        lines.append(f"- `{file.path}`: " + "; ".join(details))
    return lines


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
        if start and end:
            labels.append(f"{start}-{end}({reason})")
    return labels


def _edge_labels(value: object) -> list[str]:
    labels: list[str] = []
    if not isinstance(value, list):
        return labels
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = _clean(str(item.get("kind") or "edge"))
        target = _clean(str(item.get("target") or item.get("symbol") or ""))
        if target:
            label = f"{kind}:{target}"
            if label not in labels:
                labels.append(label)
    return labels


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

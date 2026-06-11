"""Completion-evidence updates for tool executor results."""

from __future__ import annotations

from pathlib import Path

from allCode.agent.phase_gate import satisfy_requested_artifacts
from allCode.agent.tool_evidence import normalize_evidence_path, record_source_representative_metadata
from allCode.core.models import ToolResult
from allCode.core.result import CompletionEvidence, DocumentManifest


def update_completion_evidence(result: ToolResult, evidence: CompletionEvidence, *, workspace_root: str) -> None:
    if result.name == "search_files":
        _record_search_result(result, evidence)
    if result.name in {"glob_files", "list_tree"}:
        _record_inventory_result(result, evidence)
    if result.name == "source_overview":
        _record_source_overview_result(result, evidence, workspace_root=workspace_root)
    if result.name == "read_file":
        _record_read_result(result, evidence, workspace_root=workspace_root)
    if result.name == "web_search" and result.error_type == "web_search_unavailable":
        query = str(result.metadata.get("query") or "")
        if query and query not in evidence.web_unavailable_queries:
            evidence.web_unavailable_queries.append(query)
    _record_validation_result(result, evidence)
    satisfy_requested_artifacts(evidence, workspace_root=workspace_root)
    if not result.ok:
        return
    _record_noop_result(result, evidence)
    created = [str(path) for path in result.metadata.get("created_files", [])]
    changed = [str(path) for path in result.metadata.get("changed_files", [])]
    deleted = [str(path) for path in result.metadata.get("deleted_files", [])]
    _extend_unique(evidence.created_files, created)
    _extend_unique(evidence.changed_files, changed)
    _extend_unique(evidence.deleted_files, deleted)
    document_manifest = _document_manifest_from_paths([*created, *changed], turn_id="")
    if document_manifest is not None:
        evidence.document_manifest = document_manifest
    if evidence.validation_passed is True:
        evidence.status = "validated"
    elif evidence.has_resolution_evidence():
        evidence.status = "changed"
    satisfy_requested_artifacts(evidence, workspace_root=workspace_root)


def _record_search_result(result: ToolResult, evidence: CompletionEvidence) -> None:
    query = str(result.metadata.get("query") or result.metadata.get("search_query") or "")
    if not query:
        observation = result.metadata.get("observation")
        if isinstance(observation, dict):
            query = str(observation.get("query") or "")
    if result.metadata.get("evidence_count") == 0:
        fallback_query = query or _search_query_from_content(result.content)
        if fallback_query and fallback_query not in evidence.zero_result_queries:
            evidence.zero_result_queries.append(fallback_query)
    for match in result.metadata.get("matches", []):
        if not isinstance(match, dict):
            continue
        path = str(match.get("path") or "")
        if path and path not in evidence.search_candidate_paths:
            evidence.search_candidate_paths.append(path)


def _record_inventory_result(result: ToolResult, evidence: CompletionEvidence) -> None:
    for entry in result.metadata.get("results", result.metadata.get("entries", [])):
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") not in {None, "file"}:
            continue
        path = str(entry.get("path") or "")
        if path and path not in evidence.search_candidate_paths:
            evidence.search_candidate_paths.append(path)


def _record_source_overview_result(result: ToolResult, evidence: CompletionEvidence, *, workspace_root: str) -> None:
    coverage = result.metadata.get("coverage")
    if isinstance(coverage, dict):
        evidence.source_analysis_coverage = dict(coverage)
        if bool(coverage.get("truncated")):
            evidence.source_overview_truncated = True
    for path in result.metadata.get("representative_reads", []):
        if not isinstance(path, str) or not path:
            continue
        normalized = normalize_evidence_path(path, workspace_root=workspace_root)
        if normalized and normalized not in evidence.source_representative_candidates:
            evidence.source_representative_candidates.append(normalized)
        if path not in evidence.search_candidate_paths:
            evidence.search_candidate_paths.append(path)
    record_source_representative_metadata(result.metadata, evidence, workspace_root=workspace_root)
    roles = result.metadata.get("package_roles")
    if isinstance(roles, list):
        for role in roles:
            if not isinstance(role, dict):
                continue
            normalized_role = dict(role)
            normalized_path = normalize_evidence_path(str(normalized_role.get("path") or ""), workspace_root=workspace_root)
            if normalized_path:
                normalized_role["path"] = normalized_path
            if normalized_role and normalized_role not in evidence.source_package_roles:
                evidence.source_package_roles.append(normalized_role)
    for path in result.metadata.get("suggested_reads", []):
        if isinstance(path, str) and path and path not in evidence.search_candidate_paths:
            evidence.search_candidate_paths.append(path)


def _record_read_result(result: ToolResult, evidence: CompletionEvidence, *, workspace_root: str) -> None:
    path = str(result.metadata.get("file_path") or "")
    if path and path not in evidence.inspected_paths:
        evidence.inspected_paths.append(path)
    normalized = normalize_evidence_path(path, workspace_root=workspace_root)
    if normalized and normalized in evidence.source_representative_candidates and normalized not in evidence.representative_read_paths:
        evidence.representative_read_paths.append(normalized)
    if result.error_type == "not_found" and path and path not in evidence.not_found_targets:
        evidence.not_found_targets.append(path)


def _record_validation_result(result: ToolResult, evidence: CompletionEvidence) -> None:
    command = result.metadata.get("command")
    if not result.metadata.get("validation_command") or not isinstance(command, str):
        return
    if command not in evidence.validation_commands:
        evidence.validation_commands.append(command)
    evidence.validation_passed = bool(result.metadata.get("validation_passed"))
    failure = result.metadata.get("validation_failure")
    if isinstance(failure, dict):
        for symbol in failure.get("failing_symbols", []):
            if isinstance(symbol, str) and symbol and symbol not in evidence.validation_failure_symbols:
                evidence.validation_failure_symbols.append(symbol)
    if evidence.validation_passed is True:
        evidence.status = "validated"


def _record_noop_result(result: ToolResult, evidence: CompletionEvidence) -> None:
    noop_targets = [str(path) for path in result.metadata.get("noop_targets", [])]
    if not result.metadata.get("safe_noop"):
        return
    evidence.safe_noop = True
    evidence.noop_reason = str(result.metadata.get("noop_reason") or result.error_type or "safe_noop")
    for path in noop_targets:
        if path not in evidence.noop_targets:
            evidence.noop_targets.append(path)


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _search_query_from_content(content: str) -> str:
    marker = "No matches found for query "
    if marker not in content:
        return ""
    tail = content.split(marker, 1)[1]
    if not tail:
        return ""
    quote = tail[0]
    if quote not in {"'", '"'}:
        return tail.split(" ", 1)[0].strip(". ")
    return tail[1:].split(quote, 1)[0].strip()


def _document_manifest_from_paths(paths: list[str], *, turn_id: str) -> DocumentManifest | None:
    for raw_path in reversed(paths):
        path = Path(raw_path)
        if path.suffix.lower() not in {".md", ".txt", ".rst"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        headings = _document_headings(content)
        title = headings[0] if headings else path.stem.replace("_", " ").replace("-", " ").strip()
        return DocumentManifest(
            path=str(path),
            title=title,
            artifact_kind="markdown" if path.suffix.lower() == ".md" else "text",
            section_headings=headings[:20],
            updated_at_turn_id=turn_id,
        )
    return None


def _document_headings(content: str) -> list[str]:
    headings: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title and title not in headings:
                headings.append(title)
        if len(headings) >= 20:
            break
    return headings

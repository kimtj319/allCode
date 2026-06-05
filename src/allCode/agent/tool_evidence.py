"""Completion-evidence updates derived from tool observations."""

from __future__ import annotations

import re
from pathlib import Path

from allCode.agent.related_tests import record_related_test_discovery
from allCode.core.models import ToolResult
from allCode.core.result import CompletionEvidence, RepairTarget, RequestedArtifact


class ToolEvidenceRecorder:
    """Updates CompletionEvidence without owning tool execution policy."""

    def record(
        self,
        result: ToolResult,
        evidence: CompletionEvidence,
        *,
        workspace_root: str,
    ) -> None:
        self._record_source_overview(result, evidence, workspace_root=workspace_root)
        self._record_validation_failure(result, evidence, workspace_root=workspace_root)
        record_related_test_discovery(result, evidence, workspace_root=workspace_root)
        self._record_patch_strategy(result, evidence, workspace_root=workspace_root)
        self._record_public_symbols(result, evidence, workspace_root=workspace_root)
        self._clear_repair_after_success(result, evidence, workspace_root=workspace_root)

    @staticmethod
    def _record_source_overview(
        result: ToolResult,
        evidence: CompletionEvidence,
        *,
        workspace_root: str,
    ) -> None:
        observation = result.metadata.get("observation")
        if result.name in {"read_file", "search_files", "list_directory", "glob_files", "list_tree", "source_overview", "source_probe"}:
            evidence.inspect_observation_count += 1
        if isinstance(observation, dict) and observation.get("kind") == "source_probe":
            raw_target = str(observation.get("target") or result.metadata.get("file_path") or "")
            target = normalize_evidence_path(raw_target, workspace_root=workspace_root)
            if target and target not in evidence.inspected_paths:
                evidence.inspected_paths.append(target)
            if target and target not in evidence.representative_read_paths:
                evidence.representative_read_paths.append(target)
            return
        if not isinstance(observation, dict) or observation.get("kind") != "source_overview":
            return
        overview_target = normalize_evidence_path(
            str(observation.get("target") or result.metadata.get("target") or ""),
            workspace_root=workspace_root,
        )
        if overview_target and overview_target not in evidence.source_overview_targets:
            evidence.source_overview_targets.append(overview_target)
        for path in result.metadata.get("source_overview_paths", result.metadata.get("overview_paths", [])):
            if not isinstance(path, str):
                continue
            normalized = normalize_evidence_path(path, workspace_root=workspace_root)
            if normalized and normalized not in evidence.source_overview_paths:
                evidence.source_overview_paths.append(normalized)
        for summary in result.metadata.get("source_overview_summaries", []):
            if isinstance(summary, str) and summary and summary not in evidence.source_overview_summaries:
                evidence.source_overview_summaries.append(summary[:500])
        if bool(result.metadata.get("truncated")):
            evidence.source_overview_truncated = True
        coverage = result.metadata.get("coverage")
        if isinstance(coverage, dict):
            evidence.source_analysis_coverage = dict(coverage)
            if bool(coverage.get("truncated")):
                evidence.source_overview_truncated = True
        for raw_path in result.metadata.get("representative_reads", []):
            if not isinstance(raw_path, str):
                continue
            path = normalize_evidence_path(raw_path, workspace_root=workspace_root)
            if path and path not in evidence.source_representative_candidates:
                evidence.source_representative_candidates.append(path)
        record_source_representative_metadata(result.metadata, evidence, workspace_root=workspace_root)
        roles = result.metadata.get("package_roles")
        if isinstance(roles, list):
            for role in roles:
                if not isinstance(role, dict):
                    continue
                normalized = dict(role)
                path = normalize_evidence_path(str(normalized.get("path") or ""), workspace_root=workspace_root)
                if path:
                    normalized["path"] = path
                if normalized and normalized not in evidence.source_package_roles:
                    evidence.source_package_roles.append(normalized)

    @staticmethod
    def _record_validation_failure(
        result: ToolResult,
        evidence: CompletionEvidence,
        *,
        workspace_root: str,
    ) -> None:
        failure = result.metadata.get("validation_failure")
        if not isinstance(failure, dict):
            return
        command = str(failure.get("command") or "")
        if command:
            evidence.validation_failure_command = command
        excerpt = str(failure.get("traceback_excerpt") or failure.get("assertion_excerpt") or failure.get("summary") or "")
        if excerpt:
            evidence.validation_failure_excerpt = excerpt[:1200]
        for symbol in failure.get("failing_symbols", []):
            if isinstance(symbol, str) and symbol and symbol not in evidence.validation_failure_symbols:
                evidence.validation_failure_symbols.append(symbol)
        for expectation in failure.get("public_api_expectations", []):
            if isinstance(expectation, str) and expectation and expectation not in evidence.public_api_expectations:
                evidence.public_api_expectations.append(expectation)
        counted_targets: set[str] = set()
        for raw_target in failure.get("failing_targets", []):
            if not isinstance(raw_target, dict):
                continue
            try:
                target = RepairTarget.model_validate(raw_target)
            except Exception:
                continue
            normalized = normalize_evidence_path(target.file_path, workspace_root=workspace_root)
            target = target.model_copy(update={"file_path": normalized})
            key = (target.file_path, target.line_number, target.symbol)
            if target.file_path not in counted_targets:
                evidence.validation_failure_counts[target.file_path] = (
                    evidence.validation_failure_counts.get(target.file_path, 0) + 1
                )
                counted_targets.add(target.file_path)
            if not any(
                (existing.file_path, existing.line_number, existing.symbol) == key
                for existing in evidence.validation_failure_targets
            ):
                evidence.validation_failure_targets.append(target)
            if target.reason == "missing_module":
                _add_requested_source_artifact(evidence, target.file_path)

    @staticmethod
    def _record_patch_strategy(
        result: ToolResult,
        evidence: CompletionEvidence,
        *,
        workspace_root: str,
    ) -> None:
        if result.error_type not in {"patch_ambiguous", "patch_strategy_required"}:
            return
        raw_path = str(result.metadata.get("file_path") or result.metadata.get("target") or "")
        if not raw_path:
            observation = result.metadata.get("observation")
            if isinstance(observation, dict):
                raw_path = str(observation.get("target") or "")
        path = normalize_evidence_path(raw_path, workspace_root=workspace_root)
        if path and path not in evidence.patch_ambiguous_files:
            evidence.patch_ambiguous_files.append(path)

    @staticmethod
    def _clear_repair_after_success(
        result: ToolResult,
        evidence: CompletionEvidence,
        *,
        workspace_root: str,
    ) -> None:
        if result.name == "run_tests" and result.metadata.get("validation_passed") is True:
            evidence.validation_failure_symbols.clear()
            evidence.validation_failure_targets.clear()
            evidence.validation_failure_command = ""
            evidence.validation_failure_excerpt = ""
            evidence.validation_failure_counts.clear()
            evidence.public_api_expectations.clear()
            evidence.patch_ambiguous_files.clear()
            return
        if result.name not in {"write_file", "patch_file"} or not result.ok:
            return
        touched = [
            str(path)
            for field in ("changed_files", "created_files")
            for path in result.metadata.get(field, [])
            if path
        ]
        raw = str(result.metadata.get("file_path") or "")
        if raw and not touched:
            touched.append(raw)
        normalized_touched = {
            normalize_evidence_path(path, workspace_root=workspace_root)
            for path in touched
            if path
        }
        if not normalized_touched:
            return
        evidence.patch_ambiguous_files = [
            path
            for path in evidence.patch_ambiguous_files
            if normalize_evidence_path(path, workspace_root=workspace_root) not in normalized_touched
        ]
        evidence.validation_failure_targets = [
            target
            for target in evidence.validation_failure_targets
            if normalize_evidence_path(target.file_path, workspace_root=workspace_root) not in normalized_touched
        ]

    @staticmethod
    def _record_public_symbols(
        result: ToolResult,
        evidence: CompletionEvidence,
        *,
        workspace_root: str,
    ) -> None:
        if result.name not in {"write_file", "patch_file"} or not result.ok:
            return
        touched = [
            normalize_evidence_path(str(path), workspace_root=workspace_root)
            for field in ("changed_files", "created_files")
            for path in result.metadata.get(field, [])
            if path
        ]
        if touched and not any(_looks_source_path(path) for path in touched):
            return
        diff = ""
        transaction = result.metadata.get("transaction")
        if isinstance(transaction, dict):
            diff = str(transaction.get("diff") or "")
        candidates = _public_python_symbols_from_diff(diff)
        for symbol in candidates:
            if symbol.lower() not in {item.lower() for item in evidence.feature_objectives}:
                evidence.feature_objectives.append(symbol)


def normalize_evidence_path(path: str, *, workspace_root: str) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    candidate = Path(value)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.expanduser().resolve().relative_to(Path(workspace_root).expanduser().resolve()).as_posix()
    except (OSError, ValueError):
        return candidate.as_posix()


def record_source_representative_metadata(
    metadata: dict,
    evidence: CompletionEvidence,
    *,
    workspace_root: str,
) -> None:
    reasons = metadata.get("representative_reasons")
    if isinstance(reasons, list):
        for item in reasons:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            path = normalize_evidence_path(str(normalized.get("path") or ""), workspace_root=workspace_root)
            if not path:
                continue
            normalized["path"] = path
            raw_reasons = normalized.get("reasons")
            if isinstance(raw_reasons, list):
                normalized["reasons"] = [str(reason) for reason in raw_reasons if str(reason).strip()][:8]
            if normalized and normalized not in evidence.source_representative_reasons:
                evidence.source_representative_reasons.append(normalized)
    scores = metadata.get("representative_scores")
    if isinstance(scores, dict):
        for raw_path, raw_score in scores.items():
            path = normalize_evidence_path(str(raw_path), workspace_root=workspace_root)
            if not path:
                continue
            try:
                evidence.source_representative_scores[path] = float(raw_score)
            except (TypeError, ValueError):
                continue
def _add_requested_source_artifact(evidence: CompletionEvidence, target: str) -> None:
    if not target:
        return
    key = ("source", target)
    if any((artifact.kind, artifact.target) == key for artifact in evidence.requested_artifacts):
        return
    evidence.requested_artifacts.append(
        RequestedArtifact(
            kind="source",
            target=target,
            reason="validation reported a missing import module",
        )
    )


def _public_python_symbols_from_diff(diff: str) -> list[str]:
    symbols: list[str] = []
    if not diff:
        return symbols
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        code = line[1:].strip()
        match = re.match(r"(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b", code)
        if not match:
            continue
        symbol = match.group(1)
        if symbol.startswith("_"):
            continue
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols[:12]


def _looks_source_path(path: str) -> bool:
    lowered = path.lower()
    name = Path(path).name.lower()
    if lowered.startswith("tests/") or "/tests/" in lowered or name.startswith("test_"):
        return False
    return Path(path).suffix.lower() == ".py"

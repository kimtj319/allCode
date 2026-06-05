"""Explicit phase-to-tool gate for model/tool rounds."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import Field

from allCode.agent.artifact_detection import (
    looks_like_test_artifact,
    prompt_requests_tests as _prompt_requests_tests,
)
from allCode.agent.related_tests import changed_source_paths, discovery_symbols, related_test_discovery_needed
from allCode.core.models import CoreModel
from allCode.core.path_patterns import extract_prompt_paths
from allCode.core.result import CompletionEvidence, RepairTarget, RequestedArtifact

PhaseName = Literal[
    "normal",
    "inspection_required",
    "mutation_required",
    "test_authoring_required",
    "related_test_discovery_required",
    "validation_required",
    "validation_failed",
    "repair_mutation_required",
    "revalidation_required",
    "repair_exhausted",
]

INSPECTION_TOOLS = {"read_file", "search_files", "list_directory"}
MUTATION_TOOLS = {"patch_file", "write_file"}
VALIDATION_TOOLS = {"run_tests"}
RELATED_TEST_DISCOVERY_TOOLS = {"search_files", "glob_files", "list_tree", "source_overview"}


class PhaseToolGate(CoreModel):
    phase: PhaseName = "normal"
    allowed_tool_names: set[str] = Field(default_factory=set)
    required_next_action: str = ""
    deny_hidden_tools: bool = True
    reason: str = ""
    missing_artifacts: list[str] = Field(default_factory=list)
    repair_targets: list[RepairTarget] = Field(default_factory=list)
    patch_ambiguous_files: list[str] = Field(default_factory=list)
    preferred_next_tools: list[str] = Field(default_factory=list)
    required_target_paths: list[str] = Field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.phase != "normal" and bool(self.allowed_tool_names)


def ensure_requested_artifacts(
    prompt: str,
    evidence: CompletionEvidence,
    *,
    workspace_root: str,
    routing=None,
) -> None:
    """Populate prompt-derived artifact obligations without benchmark-specific rules."""

    if routing is not None and (
        getattr(routing, "read_only_requested", False)
        or getattr(routing, "kind", "") in {"answer", "inspect"}
    ):
        satisfy_requested_artifacts(evidence, workspace_root=workspace_root)
        return
    mutation_route = routing is not None and getattr(routing, "requires_mutation", False)
    if mutation_route:
        for path in extract_prompt_paths(prompt):
            kind = _artifact_kind_for_path(path, workspace_root=workspace_root)
            _add_requested_artifact(
                evidence,
                RequestedArtifact(
                    kind=kind,
                    target=path,
                    reason="explicit path mentioned in mutation prompt",
                ),
            )
    if mutation_route and _prompt_requests_tests(prompt):
        _add_requested_artifact(
            evidence,
            RequestedArtifact(
                kind="test",
                reason="prompt requests test artifacts",
            ),
        )
    if mutation_route and routing is not None and getattr(routing, "requires_validation", False):
        _add_requested_artifact(
            evidence,
            RequestedArtifact(
                kind="validation",
                reason="route requires validation",
            ),
        )
    satisfy_requested_artifacts(evidence, workspace_root=workspace_root)


def seed_known_artifact_targets(
    prompt: str,
    evidence: CompletionEvidence,
    *,
    workspace_root: str,
    source_files: Sequence[str] = (),
    test_files: Sequence[str] = (),
) -> None:
    """Promote session-known artifacts into current-turn obligations.

    This keeps multi-turn requests grounded in already-created project files
    without relying on benchmark prompt strings. A request to add or reinforce
    tests should converge on the existing test artifact instead of repeatedly
    mutating only source files.
    """

    if _prompt_requests_tests(prompt):
        for path in _existing_targets(test_files, workspace_root=workspace_root)[:3]:
            _add_requested_artifact(
                evidence,
                RequestedArtifact(
                    kind="test",
                    target=path,
                    reason="session test artifact should be updated for requested test work",
                ),
            )
    if source_files and not any(artifact.kind == "source" for artifact in evidence.requested_artifacts):
        for path in _existing_targets(source_files, workspace_root=workspace_root)[:3]:
            _add_requested_artifact(
                evidence,
                RequestedArtifact(
                    kind="source",
                    target=path,
                    reason="session source artifact provides project context",
                    satisfied=True,
                    evidence_paths=[path],
                ),
            )


def satisfy_requested_artifacts(evidence: CompletionEvidence, *, workspace_root: str) -> None:
    changed = [*evidence.created_files, *evidence.changed_files, *evidence.deleted_files]
    for artifact in evidence.requested_artifacts:
        evidence_paths = list(artifact.evidence_paths)
        satisfied = artifact.satisfied
        if artifact.kind == "validation":
            satisfied = evidence.validation_passed is True
            if satisfied:
                evidence_paths = list(evidence.validation_commands)
        elif artifact.target:
            matches = [path for path in changed if _same_artifact_target(path, artifact.target, workspace_root=workspace_root)]
            if matches:
                satisfied = True
                evidence_paths = _merge_unique(evidence_paths, matches)
        elif artifact.kind == "test":
            matches = [path for path in changed if looks_like_test_artifact(path, workspace_root=workspace_root)]
            if matches:
                satisfied = True
                evidence_paths = _merge_unique(evidence_paths, matches)
        elif artifact.kind == "document":
            matches = [path for path in changed if _artifact_kind_for_path(path, workspace_root=workspace_root) == "document"]
            if matches:
                satisfied = True
                evidence_paths = _merge_unique(evidence_paths, matches)
        elif artifact.kind == "source":
            matches = [
                path
                for path in changed
                if _artifact_kind_for_path(path, workspace_root=workspace_root) == "source"
                and not looks_like_test_artifact(path, workspace_root=workspace_root)
            ]
            if matches:
                satisfied = True
                evidence_paths = _merge_unique(evidence_paths, matches)
        artifact.satisfied = satisfied
        artifact.evidence_paths = evidence_paths


def unsatisfied_artifact_kinds(evidence: CompletionEvidence, *kinds: str) -> list[str]:
    seen: list[str] = []
    for artifact in evidence.unsatisfied_artifacts(*kinds):
        if artifact.kind not in seen:
            seen.append(artifact.kind)
    return seen


def unsatisfied_artifact_labels(evidence: CompletionEvidence, *kinds: str) -> list[str]:
    labels: list[str] = []
    for artifact in evidence.unsatisfied_artifacts(*kinds):
        label = artifact.kind if not artifact.target else f"{artifact.kind}:{artifact.target}"
        if label not in labels:
            labels.append(label)
    return labels


def mutation_artifact_required(
    prompt: str,
    evidence: CompletionEvidence,
    *,
    workspace_root: str,
    routing=None,
) -> bool:
    if routing is not None and (
        getattr(routing, "read_only_requested", False)
        or getattr(routing, "kind", "") in {"answer", "inspect"}
    ):
        return False
    ensure_requested_artifacts(prompt, evidence, workspace_root=workspace_root, routing=routing)
    return evidence.has_unsatisfied_artifacts("source", "document", "test")


def test_artifact_required(
    prompt: str,
    evidence: CompletionEvidence,
    *,
    workspace_root: str,
    routing=None,
) -> bool:
    if routing is not None and (
        getattr(routing, "read_only_requested", False)
        or getattr(routing, "kind", "") in {"answer", "inspect"}
    ):
        return False
    ensure_requested_artifacts(prompt, evidence, workspace_root=workspace_root, routing=routing)
    if evidence.has_unsatisfied_artifacts("test"):
        return True
    if not _prompt_requests_tests(prompt):
        return False
    changed = [*evidence.changed_files, *evidence.created_files]
    return not any(looks_like_test_artifact(path, workspace_root=workspace_root) for path in changed)


def build_phase_tool_gate(
    *,
    prompt: str,
    routing,
    evidence: CompletionEvidence,
    workspace_root: str,
    inspection_budget_available: bool,
    mutation_action_pending: bool,
    validation_action_pending: bool,
    validation_repair_pending: bool,
    awaiting_revalidation_after_mutation: bool,
    repair_exhausted: bool = False,
    repair_context_read_paths: set[str] | None = None,
    test_authoring_inspection_rounds: int = 0,
) -> PhaseToolGate:
    ensure_requested_artifacts(prompt, evidence, workspace_root=workspace_root, routing=routing)
    if getattr(routing, "read_only_requested", False) or getattr(routing, "kind", "") in {"answer", "inspect"}:
        return PhaseToolGate()
    if repair_exhausted:
        return PhaseToolGate(
            phase="repair_exhausted",
            allowed_tool_names=set(),
            required_next_action="Summarize the failed validation and repair attempts.",
            reason="repair attempts are exhausted",
        )
    if getattr(routing, "requires_external_knowledge", False):
        return PhaseToolGate()
    if getattr(routing, "requires_mutation", False) and mutation_artifact_required(
        prompt,
        evidence,
        workspace_root=workspace_root,
        routing=routing,
    ):
        missing_artifacts = unsatisfied_artifact_labels(evidence, "source", "document", "test")
        missing_kinds = unsatisfied_artifact_kinds(evidence, "source", "document", "test")
        missing_targets = [artifact.target for artifact in evidence.unsatisfied_artifacts("source", "document", "test") if artifact.target]
        missing_nonexistent_targets = [
            target
            for target in missing_targets
            if not _target_exists(target, workspace_root=workspace_root)
        ]
        prompt_paths = extract_prompt_paths(prompt)
        recent_source_paths = _recent_source_paths(evidence)
        has_target_context = bool(missing_targets or prompt_paths or recent_source_paths)
        inspection_round_limit = 1 if has_target_context else 2
        allow_inspection = (
            inspection_budget_available
            and not missing_nonexistent_targets
            and test_authoring_inspection_rounds < inspection_round_limit
        )
        preferred = ["write_file"] if missing_nonexistent_targets else ["write_file", "patch_file"]
        allowed = {*MUTATION_TOOLS, *INSPECTION_TOOLS} if allow_inspection else set(preferred)
        required = "Create or update the missing requested source, document, or test artifact before validation."
        phase: PhaseName = "test_authoring_required" if "test" in missing_kinds else "mutation_required"
        return PhaseToolGate(
            phase=phase,
            allowed_tool_names=allowed,
            required_next_action=required,
            reason=f"required artifact is not satisfied yet: {', '.join(missing_artifacts)}",
            missing_artifacts=missing_artifacts,
            preferred_next_tools=preferred,
            required_target_paths=missing_targets,
        )
    if validation_action_pending or awaiting_revalidation_after_mutation:
        if related_test_discovery_needed(routing, evidence, workspace_root=workspace_root):
            source_paths = changed_source_paths(evidence)
            symbols = discovery_symbols(evidence)
            return PhaseToolGate(
                phase="related_test_discovery_required",
                allowed_tool_names=set(RELATED_TEST_DISCOVERY_TOOLS),
                required_next_action="Discover related tests before running validation.",
                reason="changed source files require validation, but no related test discovery or validation command exists yet",
                preferred_next_tools=["search_files", "source_overview"],
                required_target_paths=[*source_paths, *symbols][:8],
            )
        return PhaseToolGate(
            phase="validation_required" if validation_action_pending else "revalidation_required",
            allowed_tool_names=set(VALIDATION_TOOLS),
            required_next_action="Run validation with run_tests.",
            reason="validation is required after file mutation",
        )
    if validation_repair_pending:
        from allCode.agent.phase_gate_repair import validation_repair_gate

        return validation_repair_gate(
            phase="validation_failed",
            evidence=evidence,
            workspace_root=workspace_root,
            reason="validation failed and must be repaired before revalidation",
            repair_context_read_paths=repair_context_read_paths,
        )
    if mutation_action_pending:
        ambiguous_files = list(dict.fromkeys(evidence.patch_ambiguous_files))[:3]
        if ambiguous_files and _has_inspected_patch_ambiguous(evidence, workspace_root=workspace_root):
            return PhaseToolGate(
                phase="mutation_required",
                allowed_tool_names={"write_file"},
                required_next_action="Rewrite the already inspected ambiguous patch target with write_file.",
                reason="a patch target was ambiguous after inspection; switch to full-file rewrite",
                patch_ambiguous_files=ambiguous_files,
                preferred_next_tools=["write_file"],
            )
        allowed = {"read_file", *MUTATION_TOOLS} if inspection_budget_available else set(MUTATION_TOOLS)
        return PhaseToolGate(
            phase="mutation_required",
            allowed_tool_names=allowed,
            required_next_action="Apply the requested file mutation with patch_file or write_file.",
            reason="a mutation request has not produced file-change evidence yet",
            patch_ambiguous_files=ambiguous_files,
            preferred_next_tools=["write_file", "patch_file"] if ambiguous_files else ["patch_file", "write_file"],
        )
    return PhaseToolGate()


def validation_repair_phase_gate(
    evidence: CompletionEvidence,
    *,
    workspace_root: str,
    repair_context_read_paths: set[str] | None = None,
) -> PhaseToolGate:
    """Build the repair gate used by validation control tests and round runner."""

    from allCode.agent.phase_gate_repair import validation_repair_gate

    return validation_repair_gate(
        phase="repair_mutation_required",
        evidence=evidence,
        workspace_root=workspace_root,
        reason="validation failed and a repair mutation is required before revalidation",
        repair_context_read_paths=repair_context_read_paths,
    )


def _add_requested_artifact(evidence: CompletionEvidence, artifact: RequestedArtifact) -> None:
    key = (artifact.kind, artifact.target)
    for existing in evidence.requested_artifacts:
        if (existing.kind, existing.target) == key:
            if artifact.reason and artifact.reason not in existing.reason:
                existing.reason = artifact.reason if not existing.reason else existing.reason
            return
    evidence.requested_artifacts.append(artifact)


def _artifact_kind_for_path(path: str, *, workspace_root: str) -> str:
    suffix = Path(path).suffix.lower()
    if looks_like_test_artifact(path, workspace_root=workspace_root):
        return "test"
    if suffix in {".md", ".txt", ".rst"}:
        return "document"
    return "source"


def _same_artifact_target(path: str, target: str, *, workspace_root: str) -> bool:
    normalized_path = _normalize_target(path, workspace_root=workspace_root)
    normalized_target = _normalize_target(target, workspace_root=workspace_root)
    if normalized_path == normalized_target:
        return True
    if normalized_path.endswith(f"/{normalized_target}"):
        return True
    if "/" not in normalized_target and Path(normalized_path).name == normalized_target:
        return True
    return False


def _normalize_target(path: str, *, workspace_root: str) -> str:
    candidate = Path(path)
    try:
        if candidate.is_absolute():
            return candidate.expanduser().resolve().relative_to(Path(workspace_root).expanduser().resolve()).as_posix()
    except (OSError, ValueError):
        return candidate.as_posix()
    return candidate.as_posix()


def _target_exists(path: str, *, workspace_root: str) -> bool:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path(workspace_root) / candidate
    try:
        return candidate.expanduser().resolve().exists()
    except OSError:
        return False


def target_matches_any(path: str, targets: Sequence[str], *, workspace_root: str) -> bool:
    """Return whether a tool target satisfies one of the required artifact paths."""

    if not targets:
        return True
    return any(_same_artifact_target(path, target, workspace_root=workspace_root) for target in targets)


def _existing_targets(paths: Sequence[str], *, workspace_root: str) -> list[str]:
    existing: list[str] = []
    for path in paths:
        if not path:
            continue
        if _target_exists(path, workspace_root=workspace_root) and path not in existing:
            existing.append(_normalize_target(path, workspace_root=workspace_root))
    return existing


def _recent_source_paths(evidence: CompletionEvidence) -> list[str]:
    paths: list[str] = []
    for path in [*evidence.created_files, *evidence.changed_files]:
        lowered = path.lower()
        if looks_like_test_artifact(path, workspace_root=".") or "/test" in lowered or "tests/" in lowered:
            continue
        if path not in paths:
            paths.append(path)
    return paths[:5]

def _has_inspected_patch_ambiguous(evidence: CompletionEvidence, *, workspace_root: str) -> bool:
    normalized_reads = {
        _normalize_target(path, workspace_root=workspace_root)
        for path in evidence.inspected_paths
        if path
    }
    if not normalized_reads:
        return False
    for path in evidence.patch_ambiguous_files:
        normalized = _normalize_target(path, workspace_root=workspace_root)
        if normalized in normalized_reads:
            return True
    return False


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged

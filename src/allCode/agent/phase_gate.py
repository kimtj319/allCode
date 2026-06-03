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
from allCode.core.models import CoreModel
from allCode.core.path_patterns import extract_prompt_paths
from allCode.core.result import CompletionEvidence, RepairTarget, RequestedArtifact
from allCode.agent.validation_repair import rank_repair_targets

PhaseName = Literal[
    "normal",
    "inspection_required",
    "mutation_required",
    "test_authoring_required",
    "validation_required",
    "validation_failed",
    "repair_mutation_required",
    "revalidation_required",
    "repair_exhausted",
]

INSPECTION_TOOLS = {"read_file", "search_files", "list_directory"}
MUTATION_TOOLS = {"patch_file", "write_file"}
VALIDATION_TOOLS = {"run_tests"}


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


def mutation_artifact_required(prompt: str, evidence: CompletionEvidence, *, workspace_root: str) -> bool:
    ensure_requested_artifacts(prompt, evidence, workspace_root=workspace_root)
    return evidence.has_unsatisfied_artifacts("source", "document", "test")


def test_artifact_required(prompt: str, evidence: CompletionEvidence, *, workspace_root: str) -> bool:
    ensure_requested_artifacts(prompt, evidence, workspace_root=workspace_root)
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
    if repair_exhausted:
        return PhaseToolGate(
            phase="repair_exhausted",
            allowed_tool_names=set(),
            required_next_action="Summarize the failed validation and repair attempts.",
            reason="repair attempts are exhausted",
        )
    if getattr(routing, "read_only_requested", False) or getattr(routing, "requires_external_knowledge", False):
        return PhaseToolGate()
    if getattr(routing, "requires_mutation", False) and mutation_artifact_required(prompt, evidence, workspace_root=workspace_root):
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
        return PhaseToolGate(
            phase="validation_required" if validation_action_pending else "revalidation_required",
            allowed_tool_names=set(VALIDATION_TOOLS),
            required_next_action="Run validation with run_tests.",
            reason="validation is required after file mutation",
        )
    if validation_repair_pending:
        return _validation_repair_gate(
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

    return _validation_repair_gate(
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


def _validation_repair_gate(
    *,
    phase: PhaseName,
    evidence: CompletionEvidence,
    workspace_root: str,
    reason: str,
    repair_context_read_paths: set[str] | None = None,
) -> PhaseToolGate:
    repair_targets = rank_repair_targets(
        evidence.validation_failure_targets,
        evidence=evidence,
        workspace_root=workspace_root,
    )[:3]
    source_fallback_targets = _changed_source_repair_targets(evidence, workspace_root=workspace_root)
    if source_fallback_targets and (not repair_targets or all(_is_test_target(target, workspace_root=workspace_root) for target in repair_targets)):
        repair_targets = _merge_repair_targets(source_fallback_targets, repair_targets)[:3]
    if not repair_targets:
        repair_targets = source_fallback_targets
    ambiguous_files = list(dict.fromkeys(evidence.patch_ambiguous_files))[:3]
    missing_module_targets = [target for target in repair_targets if target.reason == "missing_module"]
    unstable_targets = _unstable_repair_targets(repair_targets, evidence, workspace_root=workspace_root)
    read_paths = repair_context_read_paths or set()
    syntax_target_pending_read = _has_syntax_repair_target(repair_targets, evidence) and not _has_current_repair_read(
        repair_targets,
        ambiguous_files,
        workspace_root=workspace_root,
        repair_context_read_paths=read_paths,
    )
    ambiguous_active = _has_ambiguous_repair_target(
        repair_targets,
        ambiguous_files,
        workspace_root=workspace_root,
    ) or bool(ambiguous_files and not repair_targets)
    if missing_module_targets:
        allowed = {"write_file", "read_file"}
        preferred = ["write_file", "read_file"]
        action = "Create the missing import module source file with write_file."
    elif unstable_targets:
        has_current_read = _has_current_repair_read(
            unstable_targets,
            ambiguous_files,
            workspace_root=workspace_root,
            repair_context_read_paths=read_paths,
        )
        if has_current_read:
            allowed = {"write_file"}
            preferred = ["write_file"]
            action = "Rewrite the repeatedly failing target with write_file using the inspected file context."
        else:
            allowed = {"read_file"}
            preferred = ["read_file"]
            action = "Read the repeatedly failing validation target before full-file repair."
    elif syntax_target_pending_read:
        allowed = {"read_file"}
        preferred = ["read_file"]
        action = "Read the exact validation failure target before repair mutation."
    elif _has_syntax_repair_target(repair_targets, evidence):
        allowed = set(MUTATION_TOOLS)
        preferred = ["write_file", "patch_file"]
        action = "Repair the syntax failure target with write_file or a sufficiently contextual patch_file."
    elif ambiguous_active:
        has_current_read = _has_current_repair_read(
            repair_targets,
            ambiguous_files,
            workspace_root=workspace_root,
            repair_context_read_paths=read_paths,
        )
        if has_current_read:
            allowed = {"read_file", "write_file"}
            preferred = ["write_file", "read_file"]
            action = "Rewrite the file with write_file, or read a narrower range if more context is needed."
        else:
            allowed = {"read_file"}
            preferred = ["read_file"]
            action = "Read the ambiguous repair target range before using write_file."
    elif repair_targets:
        has_current_read = _has_current_repair_read(
            repair_targets,
            ambiguous_files,
            workspace_root=workspace_root,
            repair_context_read_paths=read_paths,
        )
        fallback_source_targets = repair_targets[0].reason == "changed_source_after_validation_failure"
        if fallback_source_targets and not has_current_read:
            allowed = {"read_file", *MUTATION_TOOLS}
            preferred = ["write_file", "patch_file", "read_file"]
            action = "Repair the changed source file, or read it first if more context is needed."
        elif has_current_read:
            allowed = set(MUTATION_TOOLS)
            preferred = ["write_file", "patch_file"]
            action = "Repair the already inspected validation target with write_file or patch_file."
        else:
            allowed = {"read_file"}
            preferred = ["read_file"]
            action = "Read the ranked validation target before repair mutation."
    else:
        allowed = {*INSPECTION_TOOLS, *MUTATION_TOOLS}
        preferred = ["read_file", "patch_file", "write_file"] if repair_targets else ["search_files", "read_file", "patch_file"]
        action = "Inspect the failure if needed, then repair with patch_file or write_file."
    return PhaseToolGate(
        phase=phase,
        allowed_tool_names=allowed,
        required_next_action=action,
        reason=reason,
        repair_targets=repair_targets,
        patch_ambiguous_files=ambiguous_files,
        preferred_next_tools=preferred,
    )


def _has_ambiguous_repair_target(
    repair_targets: list[RepairTarget],
    ambiguous_files: list[str],
    *,
    workspace_root: str,
) -> bool:
    normalized_ambiguous = {
        _normalize_target(path, workspace_root=workspace_root)
        for path in ambiguous_files
        if path
    }
    for target in repair_targets:
        normalized = _normalize_target(target.file_path, workspace_root=workspace_root)
        if normalized in normalized_ambiguous:
            return True
    return False


def _has_syntax_repair_target(repair_targets: list[RepairTarget], evidence: CompletionEvidence) -> bool:
    return bool(repair_targets) and any(
        symbol in {"SyntaxError", "IndentationError"}
        for symbol in evidence.validation_failure_symbols
    )


def _unstable_repair_targets(
    repair_targets: list[RepairTarget],
    evidence: CompletionEvidence,
    *,
    workspace_root: str,
) -> list[RepairTarget]:
    unstable: list[RepairTarget] = []
    for target in repair_targets:
        normalized = _normalize_target(target.file_path, workspace_root=workspace_root)
        count = evidence.validation_failure_counts.get(normalized) or evidence.validation_failure_counts.get(target.file_path) or 0
        if count >= 2:
            unstable.append(target.model_copy(update={"file_path": normalized}))
    return unstable[:3]


def _recent_source_paths(evidence: CompletionEvidence) -> list[str]:
    paths: list[str] = []
    for path in [*evidence.created_files, *evidence.changed_files]:
        lowered = path.lower()
        if looks_like_test_artifact(path, workspace_root=".") or "/test" in lowered or "tests/" in lowered:
            continue
        if path not in paths:
            paths.append(path)
    return paths[:5]


def _changed_source_repair_targets(evidence: CompletionEvidence, *, workspace_root: str) -> list[RepairTarget]:
    targets: list[RepairTarget] = []
    for path in [*evidence.changed_files, *evidence.created_files]:
        normalized = _normalize_target(path, workspace_root=workspace_root)
        lowered = normalized.lower()
        if not normalized or looks_like_test_artifact(normalized, workspace_root=workspace_root):
            continue
        if "/tests/" in lowered or Path(lowered).name.startswith("test_"):
            continue
        if Path(normalized).suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".java", ".go", ".rs"}:
            continue
        if not any(target.file_path == normalized for target in targets):
            targets.append(RepairTarget(file_path=normalized, reason="changed_source_after_validation_failure"))
    return targets[:3]


def _is_test_target(target: RepairTarget, *, workspace_root: str) -> bool:
    normalized = _normalize_target(target.file_path, workspace_root=workspace_root)
    lowered = normalized.lower()
    return looks_like_test_artifact(normalized, workspace_root=workspace_root) or "/tests/" in lowered or Path(lowered).name.startswith("test_")


def _merge_repair_targets(left: list[RepairTarget], right: list[RepairTarget]) -> list[RepairTarget]:
    merged: list[RepairTarget] = []
    for target in [*left, *right]:
        key = (target.file_path, target.line_number, target.symbol)
        if not any((item.file_path, item.line_number, item.symbol) == key for item in merged):
            merged.append(target)
    return merged


def _has_current_repair_read(
    repair_targets: list[RepairTarget],
    ambiguous_files: list[str],
    *,
    workspace_root: str,
    repair_context_read_paths: set[str],
) -> bool:
    normalized_reads = {
        _normalize_target(path, workspace_root=workspace_root)
        for path in repair_context_read_paths
        if path
    }
    if not normalized_reads:
        return False
    targets = [target.file_path for target in repair_targets] or ambiguous_files
    return any(_normalize_target(path, workspace_root=workspace_root) in normalized_reads for path in targets)


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

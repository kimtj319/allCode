"""Explicit phase-to-tool gate for model/tool rounds."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from allCode.agent.artifact_detection import looks_like_test_artifact
from allCode.agent.phase_gate_artifacts import (
    _normalize_target,
    _target_exists,
    ensure_requested_artifacts,
    mutation_artifact_required,
    satisfy_requested_artifacts,
    seed_known_artifact_targets,
    target_matches_any,
    test_artifact_required,
    unsatisfied_artifact_kinds,
    unsatisfied_artifact_labels,
)
from allCode.agent.related_tests import changed_source_paths, discovery_symbols, related_test_discovery_needed
from allCode.core.models import CoreModel
from allCode.core.path_patterns import extract_prompt_paths
from allCode.core.result import CompletionEvidence, RepairTarget

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

INSPECTION_TOOLS = {"read_file", "search_files", "list_directory", "list_tree", "glob_files"}
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
        # While inspection budget remains, allow the full read-only navigation set
        # (not just read_file) so the model can locate every layer of a cross-cutting
        # change before editing; once the budget is spent, lock to mutation.
        allowed = {*INSPECTION_TOOLS, *MUTATION_TOOLS} if inspection_budget_available else set(MUTATION_TOOLS)
        return PhaseToolGate(
            phase="mutation_required",
            allowed_tool_names=allowed,
            required_next_action="Apply the requested file mutation with patch_file or write_file.",
            reason="a mutation request has not produced file-change evidence yet",
            patch_ambiguous_files=ambiguous_files,
            preferred_next_tools=["write_file", "patch_file"] if ambiguous_files else ["patch_file", "write_file"],
        )
    return PhaseToolGate()


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

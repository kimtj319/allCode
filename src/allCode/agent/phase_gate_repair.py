"""Validation-repair phase gate construction."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from allCode.agent.artifact_detection import looks_like_test_artifact
from allCode.agent.validation_repair import rank_repair_targets
from allCode.core.result import CompletionEvidence, RepairTarget

if TYPE_CHECKING:
    pass


def validation_repair_gate(
    *,
    phase,
    evidence: CompletionEvidence,
    workspace_root: str,
    reason: str,
    repair_context_read_paths: set[str] | None = None,
):
    """Build a phase gate for validation repair without owning normal phase logic."""

    from allCode.agent.phase_gate import INSPECTION_TOOLS, MUTATION_TOOLS, PhaseToolGate

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
        if has_current_read or bool(read_paths):
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
        if has_current_read or bool(read_paths):
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
        # Once the model has read any file during this repair cycle it has enough
        # context to attempt the fix. Insisting it read the *exact* ranked target
        # traps the loop when the relevant file it read (e.g. the changed source)
        # differs from the ranked target (often the test), so the repair mutation
        # is never allowed and the turn fails. Treat any repair-cycle read as
        # satisfying the read-before-repair requirement.
        if fallback_source_targets and not has_current_read:
            allowed = {"read_file", *MUTATION_TOOLS}
            preferred = ["write_file", "patch_file", "read_file"]
            action = "Repair the changed source file, or read it first if more context is needed."
        elif has_current_read or bool(read_paths):
            allowed = set(MUTATION_TOOLS)
            preferred = ["write_file", "patch_file"]
            action = "Repair the inspected validation target with write_file or patch_file."
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


def _normalize_target(path: str, *, workspace_root: str) -> str:
    from allCode.agent.phase_gate import _normalize_target as normalize

    return normalize(path, workspace_root=workspace_root)

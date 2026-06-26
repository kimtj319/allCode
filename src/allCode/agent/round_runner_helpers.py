"""Small forwarding helpers for round runner orchestration."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.agent.language import ResponseLanguage, detect_response_language
from allCode.agent.phase_block import PhaseBlockHelper
from allCode.agent.revalidation import evidence_final_answer, mutation_change_complete, validated_change_complete
from allCode.agent.round_context import record_repair_context_reads
from allCode.core.models import ToolResult
from allCode.core.result import CompletionEvidence


def test_authoring_messages(helper: PhaseBlockHelper, messages, evidence: CompletionEvidence, *, phase_gate, phase_block_reason: str = ""):
    return helper.test_authoring_messages(messages, evidence, phase_gate=phase_gate, phase_block_reason=phase_block_reason)


def validation_repair_messages(helper: PhaseBlockHelper, messages, evidence: CompletionEvidence, *, phase_gate, phase_block_reason: str = ""):
    return helper.validation_repair_messages(messages, evidence, phase_gate=phase_gate, phase_block_reason=phase_block_reason)


def can_retry_phase_block(counts: dict[tuple[str, str], int], *, phase_gate, reason: str, max_attempts: int = 2) -> bool:
    return PhaseBlockHelper.can_retry(counts, phase_gate=phase_gate, reason=reason, max_attempts=max_attempts)


def phase_block_feedback(phase_gate, results: Sequence[ToolResult]) -> str:
    return PhaseBlockHelper.feedback(phase_gate, results)


def record_context_reads(results: Sequence[ToolResult], repair_context_read_paths: set[str], *, workspace_root: str) -> None:
    record_repair_context_reads(results, repair_context_read_paths, workspace_root=workspace_root)


def validated_complete(routing, evidence: CompletionEvidence) -> bool:
    return validated_change_complete(routing, evidence)


def mutation_complete(routing, evidence: CompletionEvidence) -> bool:
    return mutation_change_complete(routing, evidence)


def evidence_answer(prompt: str, evidence: CompletionEvidence, workspace_root: str) -> str:
    return evidence_final_answer(prompt, evidence, workspace_root)


def response_language(prompt: str) -> ResponseLanguage:
    return detect_response_language(prompt)


def filter_edit_tools_for_whole_file(tool_schemas, *, enabled: bool, in_validation_repair: bool):
    """Edit-format model-awareness (OFF by default = no-op).

    When ``enabled`` and NOT in a validation-repair phase, drop ``patch_file`` so
    the model must rewrite the whole file with ``write_file`` — weaker open models
    apply search/replace diffs less reliably than full rewrites (Aider), which is
    the patch-fail build-block failure mode. ``patch_file`` is kept during
    validation repair, where targeted edits matter and the repair gate already
    drives them. Never strips the last mutation tool (write_file must remain).

    Returns the input list unchanged whenever disabled, so the default path is
    byte-for-byte the current behavior. PREPARED but unproven — enable only behind
    an A/B measurement (a blanket whole-file rewrite costs more on large files).
    """
    if not enabled or in_validation_repair:
        return tool_schemas
    if not any(getattr(t, "name", "") == "patch_file" for t in tool_schemas):
        return tool_schemas
    if not any(getattr(t, "name", "") == "write_file" for t in tool_schemas):
        return tool_schemas
    return [t for t in tool_schemas if getattr(t, "name", "") != "patch_file"]

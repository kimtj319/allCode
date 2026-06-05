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

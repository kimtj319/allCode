"""Turn completion evidence and status finalization."""

from __future__ import annotations

from dataclasses import dataclass

from allCode.agent.completion_gate import build_completion_evidence, requires_change_evidence
from allCode.agent.router import RoutingDecision
from allCode.core.models import TurnInput, TurnState
from allCode.core.result import CompletionEvidence


@dataclass(frozen=True)
class LoopOutcome:
    status: str
    answer: str = ""
    error: str | None = None


@dataclass(frozen=True)
class FinalizedCompletion:
    status: str
    error_message: str | None
    evidence: CompletionEvidence
    requires_change: bool


def finalize_completion(
    *,
    turn_input: TurnInput,
    state: TurnState,
    routing: RoutingDecision,
    outcome_status: str,
    outcome_answer: str,
    outcome_error: str | None,
    base_evidence: CompletionEvidence,
) -> FinalizedCompletion:
    evidence = build_completion_evidence(
        turn_input=turn_input,
        state=state,
        outcome_status=outcome_status,
        outcome_answer=outcome_answer,
        base_evidence=base_evidence,
        routing=routing,
    )
    requires_change = requires_change_evidence(turn_input.user_prompt, routing=routing)
    status = outcome_status
    error_message = outcome_error
    if status == "success" and requires_change and not evidence.has_resolution_evidence():
        status = "failed"
        error_message = "Completion evidence missing: change request produced no file-change or safe no-op evidence."
        evidence.status = "blocked"
        evidence.final_answer_ready = False
    if status in {"success", "partial"} and routing.requires_validation and routing.requires_mutation and evidence.validation_passed is not True:
        status = "failed"
        error_message = "Validation evidence missing: validation did not pass."
        evidence.status = "blocked"
        evidence.final_answer_ready = bool(outcome_answer.strip())
    return FinalizedCompletion(
        status=status,
        error_message=error_message,
        evidence=evidence,
        requires_change=requires_change,
    )

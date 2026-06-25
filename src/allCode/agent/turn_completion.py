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
        # An open-scope / destructive request ("정리해줘", "불필요한 파일을 지워줘",
        # "최적화", "전체를 리팩터링", "필요 없는 의존성 제거") is genuinely
        # underspecified: the safe, correct outcome is a scoped proposal/clarification
        # rather than guessing-and-mutating. Treat a substantive no-mutation answer as
        # success instead of failing it for "no file change" — otherwise the harness
        # punishes exactly the safe behavior the system prompt asks for. A specific
        # change request would have mutated, so it never reaches this branch.
        if _is_open_scope_request(turn_input.user_prompt) and len(outcome_answer.strip()) >= 80:
            pass
        else:
            status = "failed"
            error_message = "Completion evidence missing: change request produced no file-change or safe no-op evidence."
            evidence.status = "blocked"
            evidence.final_answer_ready = False
    missing_artifacts = evidence.unsatisfied_artifacts("source", "test", "document", "validation")
    if status == "success" and missing_artifacts and not _can_report_validation_failure_partial(evidence, missing_artifacts, outcome_answer):
        status = "failed"
        missing = ", ".join(
            f"{artifact.kind}:{artifact.target or '*'}"
            for artifact in missing_artifacts
        )
        error_message = f"Completion evidence missing: requested artifacts are not satisfied ({missing})."
        evidence.status = "blocked"
        evidence.final_answer_ready = False
    if status == "failed" and _can_report_recoverable_model_failure_partial(evidence, outcome_error):
        status = "partial"
        evidence.status = "blocked"
        evidence.final_answer_ready = False
    if status in {"success", "partial"} and routing.requires_validation and routing.requires_mutation and evidence.validation_passed is not True:
        status = (
            "partial"
            if evidence.validation_passed is False
            and evidence.validation_commands
            and evidence.has_file_change()
            and outcome_answer.strip()
            else "failed"
        )
        error_message = "Validation evidence missing: validation did not pass."
        evidence.status = "blocked"
        # Only a "partial" (work done, validation reportable) may surface the
        # answer as-is. A "failed" turn must NOT be marked ready, or the failure
        # caveat in final_answer_for_result is skipped and a failed turn reads as
        # a clean success.
        evidence.final_answer_ready = status == "partial" and bool(outcome_answer.strip())
    return FinalizedCompletion(
        status=status,
        error_message=error_message,
        evidence=evidence,
        requires_change=requires_change,
    )


_OPEN_SCOPE_MARKERS = (
    "정리해", "정리 해", "불필요한", "필요 없는", "필요없는", "쓸데없는",
    "최적화", "리팩터링", "리팩토링", "더 좋게", "개선해", "깔끔하게",
    "배포 가능", "초기화", "다 지워", "모두 지워", "다 삭제", "모두 삭제",
    "clean up", "cleanup", "optimize", "refactor everything", "make it better",
    "remove all", "delete all", "tidy up",
)


def _is_open_scope_request(prompt: str) -> bool:
    """Underspecified, broad, or destructive imperatives where the safe outcome is
    a scoped proposal/clarification, not a guessed mutation. Deliberately narrow:
    a specific change request ("add function X to file Y") does not match and still
    requires real change evidence."""
    lowered = str(prompt or "").lower()
    return any(marker in lowered for marker in _OPEN_SCOPE_MARKERS)


def _can_report_recoverable_model_failure_partial(
    evidence: CompletionEvidence,
    outcome_error: str | None,
) -> bool:
    if not outcome_error:
        return False
    lowered = outcome_error.lower()
    recoverable_markers = (
        "could not be parsed safely",
        "malformed",
        "reasoning-only",
        "tool call arguments ended before valid json completed",
    )
    if not any(marker in lowered for marker in recoverable_markers):
        return False
    return bool(
        evidence.inspected_paths
        or evidence.search_candidate_paths
        or evidence.patch_ambiguous_files
        or evidence.not_found_targets
        or evidence.zero_result_queries
    )


def _can_report_validation_failure_partial(
    evidence: CompletionEvidence,
    missing_artifacts,
    outcome_answer: str,
) -> bool:
    return bool(
        missing_artifacts
        and all(artifact.kind == "validation" for artifact in missing_artifacts)
        and evidence.validation_passed is False
        and evidence.validation_commands
        and evidence.has_file_change()
        and outcome_answer.strip()
    )

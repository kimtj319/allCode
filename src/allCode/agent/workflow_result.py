"""Result construction helpers for generation workflow runs."""

from __future__ import annotations

from pydantic import Field

from allCode.agent.completion_checker import CompletionCheck
from allCode.agent.task_loop_digest import TaskLoopDigest
from allCode.agent.task_plan import ProjectPlan
from allCode.agent.validation_runner import ValidationResult
from allCode.agent.workflow_actions import WorkflowStepRecord
from allCode.core.models import CoreModel
from allCode.core.result import CompletionEvidence, RecoveryState, TurnResult


class GenerationWorkflowResult(CoreModel):
    plan: ProjectPlan
    turn_result: TurnResult
    validation_results: list[ValidationResult] = Field(default_factory=list)
    completion_check: CompletionCheck
    step_history: list[WorkflowStepRecord] = Field(default_factory=list)
    task_loop_digests: list[TaskLoopDigest] = Field(default_factory=list)
    repair_attempts: int = 0


def build_workflow_turn_result(
    *,
    turn_id: str,
    plan: ProjectPlan,
    completion_evidence: CompletionEvidence,
    validation_results: list[ValidationResult],
    final_check: CompletionCheck,
    final_report: str,
    step_history: list[WorkflowStepRecord],
    task_loop_digests: list[TaskLoopDigest],
    repair_attempts: int,
    recovery_states: list[RecoveryState],
) -> GenerationWorkflowResult:
    if final_check.ok:
        completion_evidence.final_answer_ready = True
        completion_evidence.status = "reported"
        status = "success"
        error_message = None
    else:
        completion_evidence.final_answer_ready = False
        completion_evidence.status = "blocked"
        status = "failed"
        error_message = "Completion check failed: " + "; ".join(final_check.errors)
        final_report = ""

    return GenerationWorkflowResult(
        plan=plan,
        turn_result=TurnResult(
            turn_id=turn_id,
            status=status,
            final_answer=final_report,
            created_files=completion_evidence.created_files,
            modified_files=completion_evidence.changed_files,
            validation_passed=completion_evidence.validation_passed,
            error_message=error_message,
            completion_evidence=completion_evidence,
            recovery_states=recovery_states,
            requires_change_evidence=True,
            validation_required=True,
        ),
        validation_results=validation_results,
        completion_check=final_check,
        step_history=step_history,
        task_loop_digests=task_loop_digests,
        repair_attempts=repair_attempts,
    )


def build_failed_workflow_result(
    *,
    turn_id: str,
    plan: ProjectPlan,
    completion_evidence: CompletionEvidence,
    validation_results: list[ValidationResult],
    exc: Exception,
    step_history: list[WorkflowStepRecord],
    task_loop_digests: list[TaskLoopDigest],
    repair_attempts: int,
    recovery_states: list[RecoveryState],
) -> GenerationWorkflowResult:
    completion_evidence.status = "blocked"
    completion_evidence.final_answer_ready = False
    return GenerationWorkflowResult(
        plan=plan,
        turn_result=TurnResult(
            turn_id=turn_id,
            status="failed",
            error_message=str(exc),
            completion_evidence=completion_evidence,
            recovery_states=recovery_states,
            requires_change_evidence=True,
            validation_required=True,
        ),
        validation_results=validation_results,
        completion_check=CompletionCheck(ok=False, errors=[str(exc)]),
        step_history=step_history,
        task_loop_digests=task_loop_digests,
        repair_attempts=repair_attempts,
    )

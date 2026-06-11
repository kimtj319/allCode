"""Repair orchestration helpers for generation workflow."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from allCode.agent.completion_checker import CompletionCheck, CompletionChecker
from allCode.agent.router import RoutingDecision
from allCode.agent.task_plan import ProjectPlan
from allCode.agent.task_loop_digest import build_task_loop_digest
from allCode.agent.validation_runner import ValidationResult
from allCode.agent.workflow_actions import WorkflowActions, WorkflowStepRecord
from allCode.agent.workflow_completion import completion_check_repairable
from allCode.core.models import TurnInput
from allCode.core.result import CompletionEvidence, RecoveryState

RunValidationStep = Callable[
    [ProjectPlan, TurnInput, str, RoutingDecision, CompletionEvidence, list[WorkflowStepRecord]],
    Awaitable[list[ValidationResult]],
]
RepairFiles = Callable[..., Awaitable[dict[str, str]]]


async def repair_until_valid(
    *,
    strategy,
    plan: ProjectPlan,
    turn_input: TurnInput,
    turn_id: str,
    routing: RoutingDecision,
    completion_evidence: CompletionEvidence,
    validation_results: list[ValidationResult],
    recovery_states: list[RecoveryState],
    step_history: list[WorkflowStepRecord],
    actions: WorkflowActions,
    run_validation_step: RunValidationStep,
    repair_files: RepairFiles,
    max_repair_attempts: int,
    completion_checker: CompletionChecker | None = None,
) -> int:
    await actions.start_step("repair", turn_id, step_history, "Repairing validation failure.")
    attempts = 0
    previous_hash = validation_results[-1].error_hash if validation_results else None
    while validation_results and not validation_results[-1].ok and attempts < max_repair_attempts:
        failure = validation_results[-1]
        attempts += 1
        failure_log = _validation_failure_log(
            failure,
            completion_checker=completion_checker,
            plan=plan,
            turn_input=turn_input,
            completion_evidence=completion_evidence,
            validation_results=validation_results,
        )
        recovery_states.append(
            RecoveryState(reason="validation_failed", attempts=attempts, last_error=failure_log)
        )
        digest = build_task_loop_digest(
            turn_input=turn_input,
            routing=routing,
            evidence=completion_evidence,
            recovery_states=recovery_states,
            plan=plan,
            current_step="repair",
            next_required_action="Repair the latest validation failure and preserve already completed artifacts.",
        )
        files = await repair_files(
            strategy,
            plan,
            failure_log,
            turn_input,
            task_digest=digest.render(),
        )
        if not files:
            recovery_states[-1] = recovery_states[-1].model_copy(update={"blocked": True})
            break
        await actions.write_repair_files(files, plan, turn_input, turn_id, routing, completion_evidence)
        validation_results.extend(
            await run_validation_step(plan, turn_input, turn_id, routing, completion_evidence, step_history)
        )
        current_hash = validation_results[-1].error_hash
        if validation_results[-1].ok:
            break
        if current_hash and current_hash == previous_hash:
            recovery_states.append(
                RecoveryState(
                    reason="validation_failed",
                    attempts=attempts,
                    last_error=validation_results[-1].summary or validation_results[-1].error,
                    blocked=True,
                )
            )
            break
        previous_hash = current_hash
    status = "succeeded" if validation_results and validation_results[-1].ok else "failed"
    if attempts >= max_repair_attempts and validation_results and not validation_results[-1].ok:
        recovery_states.append(
            RecoveryState(
                reason="validation_failed",
                attempts=attempts,
                last_error=validation_results[-1].summary or validation_results[-1].error,
                blocked=True,
            )
        )
    await actions.finish_step("repair", turn_id, step_history, status, f"Repair attempts: {attempts}.")
    return attempts


async def repair_completion_check(
    *,
    strategy,
    check: CompletionCheck,
    plan: ProjectPlan,
    turn_input: TurnInput,
    turn_id: str,
    routing: RoutingDecision,
    completion_evidence: CompletionEvidence,
    validation_results: list[ValidationResult],
    recovery_states: list[RecoveryState],
    step_history: list[WorkflowStepRecord],
    actions: WorkflowActions,
    completion_checker: CompletionChecker,
    run_validation_step: RunValidationStep,
    repair_files: RepairFiles,
    max_repair_attempts: int,
    current_attempts: int,
) -> int:
    if not completion_check_repairable(check, completion_evidence, validation_results):
        return 0
    if current_attempts >= max_repair_attempts:
        return 0
    attempts = 0
    active_check = check
    previous_signature = ""
    while completion_check_repairable(active_check, completion_evidence, validation_results):
        if current_attempts + attempts >= max_repair_attempts:
            break
        signature = completion_check_signature(active_check)
        if attempts > 0 and signature == previous_signature:
            recovery_states.append(
                RecoveryState(
                    reason="completion_check_failed",
                    attempts=current_attempts + attempts,
                    last_error="Completion repair repeated the same errors:\n" + signature,
                    blocked=True,
                )
            )
            break
        previous_signature = signature
        attempts += 1
        failure_log = _completion_failure_log(active_check.errors)
        await actions.start_step("repair", turn_id, step_history, "Repairing completion obligation failure.")
        recovery_states.append(
            RecoveryState(reason="completion_check_failed", attempts=current_attempts + attempts, last_error=failure_log)
        )
        digest = build_task_loop_digest(
            turn_input=turn_input,
            routing=routing,
            evidence=completion_evidence,
            recovery_states=recovery_states,
            plan=plan,
            current_step="repair",
            next_required_action="Repair the completion obligation failure and rerun validation if needed.",
        )
        files = await repair_files(
            strategy,
            plan,
            failure_log,
            turn_input,
            task_digest=digest.render(),
        )
        if not files:
            recovery_states[-1] = recovery_states[-1].model_copy(update={"blocked": True})
            await actions.finish_step("repair", turn_id, step_history, "failed", "No completion repair files returned.")
            break
        await actions.write_repair_files(files, plan, turn_input, turn_id, routing, completion_evidence)
        validation_results.extend(
            await run_validation_step(plan, turn_input, turn_id, routing, completion_evidence, step_history)
        )
        active_check = completion_checker.check(
            workspace_root=turn_input.workspace.root,
            plan=plan,
            completion_evidence=completion_evidence,
            validation_results=validation_results,
        )
        status = "succeeded" if active_check.ok else "failed"
        await actions.finish_step("repair", turn_id, step_history, status, f"Completion repair attempts: {attempts}.")
        if active_check.ok:
            break
        if validation_results and validation_results[-1].ok is False:
            break
    return attempts


def completion_check_signature(check: CompletionCheck) -> str:
    return "\n".join(sorted(error.strip() for error in check.errors if error.strip()))


def _completion_failure_log(errors: list[str]) -> str:
    clean_errors = [error.strip() for error in errors if error.strip()]
    sections = ["Completion check failed:\n" + "\n".join(clean_errors)]
    targets = _preferred_repair_targets(clean_errors)
    if targets:
        sections.append("Preferred repair target files:\n" + "\n".join(f"- {target}" for target in targets))
    return "\n\n".join(section for section in sections if section.strip())


def _validation_failure_log(
    failure: ValidationResult,
    *,
    completion_checker: CompletionChecker | None,
    plan: ProjectPlan,
    turn_input: TurnInput,
    completion_evidence: CompletionEvidence,
    validation_results: list[ValidationResult],
) -> str:
    base = failure.summary or failure.error or ""
    if completion_checker is None:
        return base
    check = completion_checker.check(
        workspace_root=turn_input.workspace.root,
        plan=plan,
        completion_evidence=completion_evidence,
        validation_results=validation_results,
        validation_required=False,
    )
    completion_errors = _validation_repair_completion_errors(check.errors)
    if not completion_errors:
        return base
    sections = [base.strip()] if base.strip() else []
    sections.append(
        "Completion obligations that must be repaired before success:\n"
        + "\n".join(f"- {error}" for error in completion_errors)
    )
    targets = _preferred_repair_targets(completion_errors)
    if targets:
        sections.append("Preferred repair target files:\n" + "\n".join(f"- {target}" for target in targets))
    return "\n\n".join(sections)


def _validation_repair_completion_errors(errors: list[str]) -> list[str]:
    clean_errors = [error.strip() for error in errors if error.strip()]
    return [
        error
        for error in clean_errors
        if not error.startswith("documentation references ")
    ]


def _preferred_repair_targets(errors: list[str]) -> list[str]:
    targets: list[str] = []
    patterns = (
        r"public API obligation missing in (?P<path>[^:]+):",
        r"python syntax error in (?P<path>[^:]+):",
        r"required file missing: (?P<path>\S+)",
        r"required file empty: (?P<path>\S+)",
        r"test coverage does not exercise public API obligations in (?P<path>[^:]+):",
        r"documentation references missing file in (?P<path>[^:]+):",
        r"documentation references unsupported CLI command in (?P<path>[^:]+):",
        r"documentation references unsupported CLI option in (?P<path>[^:]+):",
    )
    for error in errors:
        for pattern in patterns:
            match = re.search(pattern, error)
            if match:
                for target in _split_target_list(match.group("path")):
                    if target and target not in targets:
                        targets.append(target)
                break
    return targets[:5]


def _split_target_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]

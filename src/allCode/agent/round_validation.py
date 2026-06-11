"""Validation fallback helpers for model round execution."""

from __future__ import annotations

from allCode.agent.finalization_helpers import blocked_summary
from allCode.agent.round_runner_helpers import evidence_answer, validated_complete
from allCode.agent.turn_completion import LoopOutcome
from allCode.core.events import PhaseTransitioned, RepairAttemptExhausted, ValidationActionInjected
from allCode.core.models import Message, ToolCall


async def apply_validation_control(runner, state, control, runtime) -> LoopOutcome | None:
    if control.repair_exhausted:
        await runner._publish(
            RepairAttemptExhausted(
                turn_id=state.turn_id,
                message="Validation repair attempts are exhausted.",
                data=control.model_dump(mode="json"),
            )
        )
        return LoopOutcome(
            status="partial",
            answer=blocked_summary(runner._prompt_builder, runtime.messages, "validation_repair_attempts_exhausted"),
            error="Validation repair attempts are exhausted.",
        )
    runtime.validation_action_pending = control.validation_action_pending
    runtime.validation_repair_pending = control.validation_repair_pending
    runtime.mutation_action_pending = runtime.mutation_action_pending or control.mutation_action_pending
    runtime.awaiting_revalidation_after_mutation = control.awaiting_revalidation_after_mutation
    if control.phase != "normal":
        await runner._publish(
            PhaseTransitioned(
                turn_id=state.turn_id,
                message=f"Round phase transitioned: {control.phase}.",
                data=control.model_dump(mode="json"),
            )
        )
    return None


async def maybe_inject_validation(
    runner,
    turn_input,
    state,
    runtime,
    loop_guard,
    recovery,
    evidence,
    routing,
    phase_gate,
    round_index,
    control,
) -> LoopOutcome | None:
    should_inject = control.should_inject_validation_action or runner._should_inject_validation_action(
        round_index,
        routing,
        evidence,
        recovery,
        validation_action_pending=runtime.validation_action_pending,
        awaiting_revalidation_after_mutation=runtime.awaiting_revalidation_after_mutation,
    )
    if not should_inject:
        return None
    state.phase = "tools"
    await runner._publish(
        ValidationActionInjected(
            turn_id=state.turn_id,
            message="Validation action injected after model did not call run_tests.",
            data={"round": round_index + 1, "reason": control.reason or "validation action pending"},
        )
    )
    await runner._record_recovery(
        state,
        recovery,
        "validation_failed",
        attempts=1,
        last_error="validation action injected after model did not call run_tests",
    )
    validation_results = await runner._execute_validation_fallback(
        turn_input,
        state,
        loop_guard,
        recovery,
        evidence,
        routing,
        phase_gate=phase_gate,
    )
    validation_call = ToolCall(id=validation_results[0].call_id, name="run_tests", arguments={})
    runtime.messages.append(Message(role="assistant", content="", tool_calls=[validation_call]))
    runtime.messages = runner._prompt_builder.append_tool_results(runtime.messages, validation_results)
    runtime.validation_action_pending = False
    runtime.awaiting_revalidation_after_mutation = False
    if any(result.name == "run_tests" and result.metadata.get("validation_passed") is False for result in validation_results):
        runtime.validation_repair_pending = True
        runtime.mutation_action_pending = True
        runtime.mutation_attempted_after_failed_validation = False
        runtime.mutation_succeeded_after_failed_validation = False
    if validated_complete(routing, evidence):
        return LoopOutcome(status="success", answer=evidence_answer(turn_input.user_prompt, evidence, turn_input.workspace.root))
    return None

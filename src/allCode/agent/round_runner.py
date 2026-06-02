"""Model round execution and recovery handling."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from allCode.agent.finalization_helpers import (
    blocked_summary,
    has_blocking_tool_result,
    message_chars,
    tool_observation_chars,
)
from allCode.agent.grounding import grounding_required, next_candidate_read_call
from allCode.agent.phase_gate import build_phase_tool_gate, looks_like_test_artifact, test_artifact_required
from allCode.agent.prompt_builder import PromptBuilder
from allCode.agent.recovery import RecoveryTracker, ToolLoopGuard, needs_validation_repair
from allCode.agent.round_state import RoundStateSnapshot
from allCode.agent.stream_collector import ModelStreamCollector
from allCode.agent.tool_call_processor import ToolCallProcessor
from allCode.agent.turn_completion import LoopOutcome
from allCode.agent.validation_controller import ValidationRepairController
from allCode.agent.validation_repair import validation_repair_needed
from allCode.core.event_bus import EventBus
from allCode.core.events import (
    ModelMetricsRecorded,
    ModelRequestPrepared,
    ModelResponseParsed,
    ModelStreamStarted,
    PhaseTransitioned,
    RecoveryStateUpdated,
    RepairAttemptExhausted,
    ValidationActionInjected,
)
from allCode.core.models import Message, ToolCall, ToolResult, TurnInput, TurnState
from allCode.core.result import CompletionEvidence
from allCode.llm.response_parser import ResponseParser


MUTATION_TOOL_NAMES = {"patch_file", "write_file", "delete_path"}
INSPECTION_TOOL_NAMES = {"read_file", "search_files", "list_directory"}


class RoundRunner:
    """Runs model/tool rounds while keeping recovery state observable."""

    def __init__(
        self,
        *,
        llm_client=None,
        settings=None,
        event_bus: EventBus,
        prompt_builder: PromptBuilder,
        tool_call_processor: ToolCallProcessor,
        stream_collector: ModelStreamCollector,
        max_rounds: int = 12,
        inspect_action_budget: int = 5,
        inspect_round_budget: int = 4,
    ) -> None:
        self._event_bus = event_bus
        self._prompt_builder = prompt_builder
        self._tool_call_processor = tool_call_processor
        self._stream_collector = stream_collector
        self._max_rounds = max_rounds
        self._inspect_action_budget = inspect_action_budget
        self._inspect_round_budget = inspect_round_budget
        self._parser = ResponseParser()
        self._validation_controller = ValidationRepairController()

    async def run_rounds(
        self,
        turn_input: TurnInput,
        state: TurnState,
        recovery: RecoveryTracker,
        loop_guard: ToolLoopGuard,
        completion_evidence: CompletionEvidence,
        routing,
        *,
        force_mutation_action: bool = False,
    ) -> LoopOutcome:
        messages = list(state.messages)
        pseudo_tool_retry_used = False
        validation_repair_pending = False
        validation_action_pending = False
        mutation_action_pending = force_mutation_action
        awaiting_revalidation_after_mutation = False
        malformed_tool_retries = 0
        inspection_actions = 0
        inspection_rounds = 0
        completion_evidence.grounding_required = grounding_required(turn_input.user_prompt, routing)

        for round_index in range(self._max_rounds):
            state.phase = "model"
            more_mutation_before_validation = test_artifact_required(
                turn_input.user_prompt,
                completion_evidence,
                workspace_root=turn_input.workspace.root,
            )
            if completion_evidence.validation_passed is True:
                validation_action_pending = False
            if validation_action_pending or awaiting_revalidation_after_mutation:
                validation_repair_pending = False
            else:
                validation_repair_pending = validation_repair_pending or validation_repair_needed(
                    routing,
                    completion_evidence,
                )
            control = self._validation_controller.decide(
                snapshot=RoundStateSnapshot(
                    round_index=round_index,
                    phase="normal",
                    mutation_since_last_validation=completion_evidence.has_file_change()
                    and completion_evidence.validation_passed is not True,
                    validation_attempts=len(completion_evidence.validation_commands),
                    repair_attempts=recovery.validation_repair_requests,
                    last_validation_status=completion_evidence.validation_passed,
                ),
                routing=routing,
                evidence=completion_evidence,
                validation_action_pending=validation_action_pending,
                validation_repair_pending=validation_repair_pending,
                mutation_action_pending=mutation_action_pending,
                awaiting_revalidation_after_mutation=awaiting_revalidation_after_mutation,
                more_mutation_before_validation=more_mutation_before_validation,
                validation_action_requested=recovery.validation_action_requested,
                max_rounds=self._max_rounds,
            )
            if control.repair_exhausted:
                await self._publish(
                    RepairAttemptExhausted(
                        turn_id=state.turn_id,
                        message="Validation repair attempts are exhausted.",
                        data=control.model_dump(mode="json"),
                    )
                )
                return LoopOutcome(
                    status="partial",
                    answer=blocked_summary(
                        self._prompt_builder,
                        messages,
                        "validation_repair_attempts_exhausted",
                    ),
                    error="Validation repair attempts are exhausted.",
                )
            validation_action_pending = control.validation_action_pending
            validation_repair_pending = control.validation_repair_pending
            mutation_action_pending = mutation_action_pending or control.mutation_action_pending
            awaiting_revalidation_after_mutation = control.awaiting_revalidation_after_mutation
            if control.phase != "normal":
                await self._publish(
                    PhaseTransitioned(
                        turn_id=state.turn_id,
                        message=f"Round phase transitioned: {control.phase}.",
                        data=control.model_dump(mode="json"),
                    )
                )
            inspection_budget_available = self._inspection_budget_available(
                inspection_actions,
                inspection_rounds,
            )
            lock_to_mutation = mutation_action_pending and (
                not validation_repair_pending
                and (not inspection_budget_available or recovery.mutation_action_requests >= 2)
            )
            phase_gate = build_phase_tool_gate(
                prompt=turn_input.user_prompt,
                routing=routing,
                evidence=completion_evidence,
                workspace_root=turn_input.workspace.root,
                inspection_budget_available=inspection_budget_available,
                mutation_action_pending=lock_to_mutation,
                validation_action_pending=validation_action_pending,
                validation_repair_pending=validation_repair_pending,
                awaiting_revalidation_after_mutation=awaiting_revalidation_after_mutation,
            )
            if control.should_inject_validation_action or self._should_inject_validation_action(
                round_index,
                routing,
                completion_evidence,
                recovery,
                validation_action_pending=validation_action_pending,
                awaiting_revalidation_after_mutation=awaiting_revalidation_after_mutation,
            ):
                state.phase = "tools"
                await self._publish(
                    ValidationActionInjected(
                        turn_id=state.turn_id,
                        message="Validation action injected after model did not call run_tests.",
                        data={"round": round_index + 1, "reason": control.reason or "validation action pending"},
                    )
                )
                await self._record_recovery(
                    state,
                    recovery,
                    "validation_failed",
                    attempts=1,
                    last_error="validation action injected after model did not call run_tests",
                )
                validation_results = await self._execute_validation_fallback(
                    turn_input,
                    state,
                    loop_guard,
                    recovery,
                    completion_evidence,
                    routing,
                    phase_gate=phase_gate,
                )
                validation_call = ToolCall(id=validation_results[0].call_id, name="run_tests", arguments={})
                messages.append(Message(role="assistant", content="", tool_calls=[validation_call]))
                messages = self._prompt_builder.append_tool_results(messages, validation_results)
                validation_action_pending = False
                awaiting_revalidation_after_mutation = False
                if any(result.name == "run_tests" and result.metadata.get("validation_passed") is False for result in validation_results):
                    validation_repair_pending = True
                    mutation_action_pending = True
                if self._validated_change_complete(routing, completion_evidence):
                    return LoopOutcome(
                        status="success",
                        answer=self._evidence_final_answer(turn_input.user_prompt, completion_evidence, turn_input.workspace.root),
                    )
                continue
            tool_schemas = self._tool_call_processor.tool_schemas_for_routing(
                routing,
                suppress_validation=validation_repair_pending,
                only_mutation=lock_to_mutation,
                only_validation=validation_action_pending,
                include_validation_probe=(
                    lock_to_mutation
                    and routing.requires_validation
                    and not completion_evidence.validation_commands
                ),
                allowed_only=phase_gate.allowed_tool_names if phase_gate.active else None,
            )
            allowed_tool_names = {schema.name for schema in tool_schemas}
            has_tool_results = any(message.role == "tool" for message in messages)
            stream_phase = "continuation" if has_tool_results else ("retry" if recovery.states else "initial")

            await self._publish(
                ModelRequestPrepared(
                    turn_id=state.turn_id,
                    message=f"Model request prepared for round {round_index + 1}.",
                    data={
                        "round": round_index + 1,
                        "message_count": len(messages),
                        "message_chars": message_chars(messages),
                        "tool_observation_chars": tool_observation_chars(messages),
                        "allowed_tools": sorted(allowed_tool_names),
                        "routing": routing.model_dump(mode="json"),
                        "phase_gate": phase_gate.model_dump(mode="json"),
                    },
                )
            )
            await self._publish(
                ModelStreamStarted(
                    turn_id=state.turn_id,
                    message=f"Model stream started for round {round_index + 1}.",
                    data={
                        "round": round_index + 1,
                        "retry": stream_phase == "retry",
                        "stream_phase": stream_phase,
                    },
                )
            )

            stream_text = not (routing.requires_external_knowledge and not has_tool_results)
            events, stream_timed_out = await self._stream_collector.collect(
                state=state,
                messages=messages,
                recovery=recovery,
                tool_schemas=tool_schemas,
                stream_text=stream_text,
            )
            if stream_timed_out and not events and recovery.can_retry_stream_timeout():
                state.phase = "recovery"
                messages = self._prompt_builder.empty_response_retry(messages)
                continue
            if stream_timed_out and not events:
                return LoopOutcome(status="failed", error="Model stream timed out without usable output.")

            parsed = self._parser.parse_events(events)
            await self._publish(
                ModelResponseParsed(
                    turn_id=state.turn_id,
                    message=f"Model response parsed: {parsed.status}.",
                    data={
                        "status": parsed.status,
                        "finish_reason": parsed.finish_reason,
                        "text_length": len(parsed.text),
                        "tool_calls": [
                            {"id": tool_call.id, "name": tool_call.name}
                            for tool_call in parsed.tool_calls
                        ],
                        "usage": parsed.usage.model_dump(mode="json") if parsed.usage is not None else None,
                        "error": parsed.error,
                        "metrics": parsed.metrics,
                        "tool_argument_repairs": parsed.tool_argument_repairs,
                    },
                )
            )
            await self._publish(
                ModelMetricsRecorded(
                    turn_id=state.turn_id,
                    message=f"Model metrics recorded for round {round_index + 1}.",
                    data={
                        "round": round_index + 1,
                        "request_message_count": len(messages),
                        "request_chars": message_chars(messages),
                        "request_tool_observation_chars": tool_observation_chars(messages),
                        "response_text_chars": len(parsed.text),
                        "response_metrics": parsed.metrics,
                        "usage": parsed.usage.model_dump(mode="json") if parsed.usage is not None else None,
                    },
                )
            )
            if parsed.usage is not None:
                state.token_usage = parsed.usage

            if parsed.status == "empty_response":
                if recovery.can_retry_empty_response():
                    state.phase = "recovery"
                    await self._record_recovery(state, recovery, "empty_response", attempts=1)
                    messages = self._prompt_builder.empty_response_retry(messages)
                    continue
                await self._record_recovery(state, recovery, "empty_response", attempts=2, blocked=True)
                return LoopOutcome(status="failed", error="Model returned an empty response after retry.")

            if parsed.status == "reasoning_only":
                if routing.requires_mutation and not completion_evidence.has_resolution_evidence():
                    if recovery.can_request_mutation_action():
                        state.phase = "recovery"
                        await self._record_recovery(
                            state,
                            recovery,
                            "no_progress",
                            attempts=1,
                            last_error="model produced reasoning-only content before file mutation",
                        )
                        messages = self._prompt_builder.mutation_action_request(messages)
                        mutation_action_pending = True
                        continue
                if more_mutation_before_validation:
                    if recovery.can_request_mutation_action(max_attempts=6):
                        state.phase = "recovery"
                        await self._record_recovery(
                            state,
                            recovery,
                            "no_progress",
                            attempts=recovery.mutation_action_requests,
                            last_error="test artifact is still required before final answer",
                        )
                        messages = self._prompt_builder.mutation_action_request(messages)
                        mutation_action_pending = True
                        continue
                if validation_action_pending and completion_evidence.validation_passed is not True:
                    if recovery.can_request_validation_action():
                        state.phase = "recovery"
                        await self._record_recovery(
                            state,
                            recovery,
                            "validation_failed",
                            attempts=1,
                            last_error="file change exists but validation has not run",
                        )
                        messages = self._prompt_builder.validation_action_request(messages)
                        continue
                    return LoopOutcome(
                        status="partial",
                        answer=blocked_summary(
                            self._prompt_builder,
                            messages,
                            "validation_required_but_model_did_not_call_run_tests",
                        ),
                        error="Validation is required but the model did not call run_tests.",
                    )
                if needs_validation_repair(routing, completion_evidence) or validation_repair_needed(
                    routing,
                    completion_evidence,
                ):
                    if recovery.can_request_validation_repair():
                        state.phase = "recovery"
                        await self._record_recovery(
                            state,
                            recovery,
                            "validation_failed",
                            attempts=recovery.validation_repair_requests,
                            last_error="model produced reasoning-only content after failed validation",
                        )
                        messages = self._prompt_builder.validation_repair_request(messages)
                        validation_repair_pending = True
                        mutation_action_pending = True
                        continue
                if recovery.can_request_final_answer():
                    state.phase = "recovery"
                    await self._record_recovery(state, recovery, "reasoning_only", attempts=1)
                    messages = self._prompt_builder.final_answer_request(messages)
                    continue
                await self._record_recovery(state, recovery, "reasoning_only", attempts=2, blocked=True)
                return LoopOutcome(
                    status="partial",
                    answer=blocked_summary(
                        self._prompt_builder,
                        messages,
                        "model_returned_reasoning_only_after_retry",
                    ),
                    error="Model returned reasoning-only content after retry.",
                )

            if parsed.status == "pseudo_tool_call":
                if not pseudo_tool_retry_used:
                    pseudo_tool_retry_used = True
                    state.phase = "recovery"
                    if parsed.text.strip():
                        messages.append(Message(role="assistant", content=parsed.text.rstrip()))
                    if routing.allows_tool_use:
                        messages = self._prompt_builder.native_tool_call_retry(messages, parser_error=parsed.error)
                    else:
                        messages = self._prompt_builder.natural_language_retry(messages)
                    continue
                return LoopOutcome(
                    status="failed",
                    answer=blocked_summary(self._prompt_builder, messages, parsed.error or "pseudo_tool_call"),
                    error=parsed.error or "Model emitted pseudo tool-call text after retry.",
                )

            if parsed.status == "malformed_tool_call":
                if routing.allows_tool_use and malformed_tool_retries < 4:
                    malformed_tool_retries += 1
                    state.phase = "recovery"
                    await self._record_recovery(
                        state,
                        recovery,
                        "no_progress",
                        attempts=malformed_tool_retries,
                        last_error=f"malformed native tool call: {parsed.error or 'invalid arguments'}",
                    )
                    if parsed.text.strip():
                        messages.append(Message(role="assistant", content=parsed.text.rstrip()))
                    messages = self._prompt_builder.native_tool_call_retry(messages, parser_error=parsed.error)
                    continue
                if routing.requires_mutation and more_mutation_before_validation:
                    if recovery.can_request_mutation_action(max_attempts=6):
                        state.phase = "recovery"
                        await self._record_recovery(
                            state,
                            recovery,
                            "no_progress",
                            attempts=recovery.mutation_action_requests,
                            last_error="malformed tool call occurred before required test artifact mutation",
                        )
                        messages = self._prompt_builder.mutation_action_request(messages)
                        mutation_action_pending = True
                        continue
                if routing.requires_validation and completion_evidence.has_file_change():
                    if recovery.can_request_validation_action() or round_index >= self._max_rounds - 2:
                        state.phase = "tools"
                        await self._record_recovery(
                            state,
                            recovery,
                            "validation_failed",
                            attempts=1,
                            last_error="validation fallback injected after malformed tool calls",
                        )
                        validation_results = await self._execute_validation_fallback(
                            turn_input,
                            state,
                            loop_guard,
                            recovery,
                            completion_evidence,
                            routing,
                            phase_gate=phase_gate,
                        )
                        validation_call = ToolCall(id=validation_results[0].call_id, name="run_tests", arguments={})
                        messages.append(Message(role="assistant", content="", tool_calls=[validation_call]))
                        messages = self._prompt_builder.append_tool_results(messages, validation_results)
                        validation_action_pending = False
                        awaiting_revalidation_after_mutation = False
                        if self._validated_change_complete(routing, completion_evidence):
                            return LoopOutcome(
                                status="success",
                                answer=self._evidence_final_answer(
                                    turn_input.user_prompt,
                                    completion_evidence,
                                    turn_input.workspace.root,
                                ),
                            )
                        if any(
                            result.name == "run_tests"
                            and result.metadata.get("validation_passed") is False
                            for result in validation_results
                        ):
                            validation_repair_pending = True
                            mutation_action_pending = True
                            malformed_tool_retries = 0
                            continue
                    if recovery.can_request_validation_action():
                        state.phase = "recovery"
                        await self._record_recovery(
                            state,
                            recovery,
                            "validation_failed",
                            attempts=1,
                            last_error="malformed tool call occurred after file change before validation",
                        )
                        messages = self._prompt_builder.validation_action_request(messages)
                        validation_action_pending = True
                        continue
                return LoopOutcome(
                    status="failed",
                    answer=blocked_summary(
                        self._prompt_builder,
                        messages,
                        parsed.error or "malformed_tool_call",
                    ),
                    error=f"Model response could not be parsed safely: {parsed.error or 'malformed tool call'}",
                )

            if parsed.status == "ok_tool_calls":
                state.phase = "tools"
                results = await self._tool_call_processor.execute(
                    turn_input,
                    state,
                    parsed.tool_calls,
                    loop_guard,
                    recovery,
                    completion_evidence,
                    routing,
                    allowed_tool_names=allowed_tool_names,
                    phase_gate=phase_gate,
                )
                messages.append(Message(role="assistant", content=parsed.text, tool_calls=parsed.tool_calls))
                messages = self._prompt_builder.append_tool_results(messages, results)

                inspection_count = sum(1 for result in results if result.name in INSPECTION_TOOL_NAMES)
                if inspection_count:
                    inspection_actions += inspection_count
                    if not any(result.name in MUTATION_TOOL_NAMES and result.ok for result in results):
                        inspection_rounds += 1
                had_failed_validation_before_mutation = completion_evidence.validation_passed is False
                if any(result.ok and result.name in MUTATION_TOOL_NAMES for result in results):
                    more_mutation_before_validation = test_artifact_required(
                        turn_input.user_prompt,
                        completion_evidence,
                        workspace_root=turn_input.workspace.root,
                    )
                    mutation_action_pending = more_mutation_before_validation
                    validation_repair_pending = False
                    awaiting_revalidation_after_mutation = (
                        had_failed_validation_before_mutation
                        and routing.requires_validation
                        and completion_evidence.validation_passed is not True
                        and not more_mutation_before_validation
                    )
                    validation_action_pending = (
                        routing.requires_validation
                        and completion_evidence.validation_passed is not True
                        and not more_mutation_before_validation
                        and not awaiting_revalidation_after_mutation
                    )
                    if self._should_inject_validation_action(
                        round_index,
                        routing,
                        completion_evidence,
                        recovery,
                        validation_action_pending=validation_action_pending,
                        awaiting_revalidation_after_mutation=False,
                    ):
                        validation_results = await self._execute_validation_fallback(
                            turn_input,
                            state,
                            loop_guard,
                            recovery,
                            completion_evidence,
                            routing,
                            phase_gate=phase_gate,
                        )
                        validation_call = ToolCall(id=validation_results[0].call_id, name="run_tests", arguments={})
                        messages.append(Message(role="assistant", content="", tool_calls=[validation_call]))
                        messages = self._prompt_builder.append_tool_results(messages, validation_results)
                        validation_action_pending = False
                        if any(
                            result.name == "run_tests"
                            and result.metadata.get("validation_passed") is False
                            for result in validation_results
                        ):
                            validation_repair_pending = True
                            mutation_action_pending = True
                        if self._validated_change_complete(routing, completion_evidence):
                            return LoopOutcome(
                                status="success",
                                answer=self._evidence_final_answer(
                                    turn_input.user_prompt,
                                    completion_evidence,
                                    turn_input.workspace.root,
                                ),
                            )
                if any(result.name == "run_tests" for result in results):
                    awaiting_revalidation_after_mutation = False
                    validation_action_pending = False
                if any(result.name == "run_tests" and result.metadata.get("validation_passed") is False for result in results):
                    validation_repair_pending = True
                    mutation_action_pending = True
                    validation_action_pending = False
                if self._validated_change_complete(routing, completion_evidence):
                    return LoopOutcome(
                        status="success",
                        answer=self._evidence_final_answer(
                            turn_input.user_prompt,
                            completion_evidence,
                            turn_input.workspace.root,
                        ),
                    )
                if (
                    results
                    and all(result.error_type == "schema_denied" for result in results)
                    and phase_gate.phase
                    in {"mutation_required", "test_authoring_required", "repair_mutation_required"}
                    and recovery.can_request_mutation_action(max_attempts=6)
                ):
                    state.phase = "recovery"
                    await self._record_recovery(
                        state,
                        recovery,
                        "no_progress",
                        attempts=recovery.mutation_action_requests,
                        last_error="model selected tools outside the required mutation phase",
                    )
                    messages = self._prompt_builder.mutation_action_request(messages)
                    mutation_action_pending = True
                    continue
                grounding_call = next_candidate_read_call(
                    completion_evidence,
                    workspace_root=turn_input.workspace.root,
                )
                if grounding_call is not None:
                    grounding_results = await self._tool_call_processor.execute(
                        turn_input,
                        state,
                        [grounding_call],
                        loop_guard,
                        recovery,
                        completion_evidence,
                        routing,
                        allowed_tool_names={"read_file"},
                        phase_gate=phase_gate,
                    )
                    messages.append(Message(role="assistant", content="", tool_calls=[grounding_call]))
                    messages = self._prompt_builder.append_tool_results(messages, grounding_results)
                    inspection_actions += sum(1 for result in grounding_results if result.name in INSPECTION_TOOL_NAMES)
                    continue
                if any(result.is_final and result.ok for result in results):
                    return LoopOutcome(
                        status="success",
                        answer=next(result.content for result in results if result.is_final and result.ok),
                    )
                if has_blocking_tool_result(results):
                    return LoopOutcome(
                        status="partial",
                        answer=blocked_summary(
                            self._prompt_builder,
                            messages,
                            "tool_progress_blocked",
                        ),
                        error="Tool progress blocked by loop guard.",
                    )
                if (
                    routing.requires_mutation
                    and not completion_evidence.has_resolution_evidence()
                    and any(result.name == "read_file" and result.ok for result in results)
                    and recovery.can_request_mutation_action()
                ):
                    state.phase = "recovery"
                    await self._record_recovery(
                        state,
                        recovery,
                        "no_progress",
                        attempts=1,
                        last_error="target inspected but no mutation has run",
                    )
                    messages = self._prompt_builder.mutation_action_request(messages)
                    mutation_action_pending = True
                    continue
                continue

            if parsed.status == "length_cutoff":
                await self._record_recovery(
                    state,
                    recovery,
                    "length_cutoff",
                    attempts=1,
                    last_error="model response hit length limit",
                )
                return LoopOutcome(status="partial", answer=parsed.text.rstrip(), error="length_cutoff")

            if parsed.text.strip():
                if routing.requires_mutation and not completion_evidence.has_resolution_evidence():
                    if recovery.can_request_mutation_action():
                        state.phase = "recovery"
                        await self._record_recovery(
                            state,
                            recovery,
                            "no_progress",
                            attempts=1,
                            last_error="model answered before file mutation",
                        )
                        messages.append(Message(role="assistant", content=parsed.text.rstrip()))
                        messages = self._prompt_builder.mutation_action_request(messages)
                        mutation_action_pending = True
                        continue
                if more_mutation_before_validation:
                    if recovery.can_request_mutation_action(max_attempts=6):
                        state.phase = "recovery"
                        await self._record_recovery(
                            state,
                            recovery,
                            "no_progress",
                            attempts=recovery.mutation_action_requests,
                            last_error="model answered before required test artifact was written",
                        )
                        messages.append(Message(role="assistant", content=parsed.text.rstrip()))
                        messages = self._prompt_builder.mutation_action_request(messages)
                        mutation_action_pending = True
                        continue
                    return LoopOutcome(
                        status="partial",
                        answer=blocked_summary(
                            self._prompt_builder,
                            messages,
                            "test_artifact_required_before_validation",
                        ),
                        error="A requested test artifact is required before validation and final answer.",
                    )
                if validation_action_pending and completion_evidence.validation_passed is not True:
                    if recovery.can_request_validation_action():
                        state.phase = "recovery"
                        await self._record_recovery(
                            state,
                            recovery,
                            "validation_failed",
                            attempts=1,
                            last_error="model answered before required validation",
                        )
                        messages.append(Message(role="assistant", content=parsed.text.rstrip()))
                        messages = self._prompt_builder.validation_action_request(messages)
                        continue
                    return LoopOutcome(
                        status="partial",
                        answer=blocked_summary(
                            self._prompt_builder,
                            messages,
                            "validation_required_but_model_answered_without_run_tests",
                        ),
                        error="Validation is required but the model answered before run_tests.",
                    )
                if needs_validation_repair(routing, completion_evidence) or validation_repair_needed(
                    routing,
                    completion_evidence,
                ):
                    if recovery.can_request_validation_repair():
                        state.phase = "recovery"
                        await self._record_recovery(
                            state,
                            recovery,
                            "validation_failed",
                            attempts=recovery.validation_repair_requests,
                            last_error="model answered before validation passed",
                        )
                        messages.append(Message(role="assistant", content=parsed.text.rstrip()))
                        messages = self._prompt_builder.validation_repair_request(messages)
                        validation_repair_pending = True
                        mutation_action_pending = True
                        continue
                return LoopOutcome(status="success", answer=parsed.text.rstrip())

        return LoopOutcome(
            status="partial",
            answer=blocked_summary(self._prompt_builder, messages, "max_rounds_reached"),
            error="The turn reached the maximum number of model rounds before a final answer was produced.",
        )

    async def _record_recovery(
        self,
        state: TurnState,
        recovery: RecoveryTracker,
        reason,
        *,
        attempts: int = 0,
        last_error: str | None = None,
        blocked: bool = False,
    ) -> None:
        recovery.add_state(reason, attempts=attempts, last_error=last_error, blocked=blocked)
        latest = recovery.states[-1]
        await self._publish(
            RecoveryStateUpdated(
                turn_id=state.turn_id,
                message=f"Recovery state updated: {latest.reason}.",
                data=latest.model_dump(mode="json"),
            )
        )

    async def _publish(self, event) -> None:
        await self._event_bus.publish(event)

    def _inspection_budget_available(self, inspection_actions: int, inspection_rounds: int) -> bool:
        return (
            inspection_actions < self._inspect_action_budget
            and inspection_rounds < self._inspect_round_budget
        )

    def _should_inject_validation_action(
        self,
        round_index: int,
        routing,
        evidence: CompletionEvidence,
        recovery: RecoveryTracker,
        *,
        validation_action_pending: bool,
        awaiting_revalidation_after_mutation: bool,
    ) -> bool:
        if not (validation_action_pending or awaiting_revalidation_after_mutation):
            return False
        if not getattr(routing, "requires_validation", False) or evidence.validation_passed is True:
            return False
        if not evidence.has_file_change():
            return False
        if evidence.validation_passed is False and not awaiting_revalidation_after_mutation:
            return False
        return recovery.validation_action_requested or round_index >= self._max_rounds - 2

    async def _execute_validation_fallback(
        self,
        turn_input: TurnInput,
        state: TurnState,
        loop_guard: ToolLoopGuard,
        recovery: RecoveryTracker,
        completion_evidence: CompletionEvidence,
        routing,
        *,
        phase_gate,
    ) -> list[ToolResult]:
        call = ToolCall(id=f"validation-{uuid4().hex}", name="run_tests", arguments={})
        return await self._tool_call_processor.execute(
            turn_input,
            state,
            [call],
            loop_guard,
            recovery,
            completion_evidence,
            routing,
            allowed_tool_names={"run_tests"},
            phase_gate=phase_gate,
        )

    def _needs_more_mutation_before_validation(
        self,
        prompt: str,
        evidence: CompletionEvidence,
        *,
        workspace_root: str,
    ) -> bool:
        return test_artifact_required(prompt, evidence, workspace_root=workspace_root)

    @staticmethod
    def _looks_like_test_artifact(path: str, *, workspace_root: str) -> bool:
        return looks_like_test_artifact(path, workspace_root=workspace_root)

    @staticmethod
    def _validated_change_complete(routing, evidence: CompletionEvidence) -> bool:
        return (
            getattr(routing, "requires_mutation", False)
            and getattr(routing, "requires_validation", False)
            and evidence.has_file_change()
            and evidence.validation_passed is True
        )

    def _evidence_final_answer(
        self,
        prompt: str,
        evidence: CompletionEvidence,
        workspace_root: str,
    ) -> str:
        changed = self._relative_unique_files(
            [*evidence.created_files, *evidence.changed_files, *evidence.deleted_files],
            workspace_root,
        )
        terms = self._prompt_reference_terms(prompt)
        lines = ["작업을 완료했습니다."]
        if changed:
            lines.append("- 생성/수정 파일:")
            lines.extend(f"  - `{path}`" for path in changed[:12])
        if terms:
            lines.append("- 요청 기준: " + ", ".join(f"`{term}`" for term in terms[:8]))
        if evidence.validation_commands:
            lines.append(f"- 검증 명령: `{evidence.validation_commands[-1]}`")
        lines.append("- 검증 결과: 통과")
        lines.append("- 남은 리스크: 현재 검증 범위 밖의 런타임 환경 차이는 추가 확인이 필요합니다.")
        return "\n".join(lines)

    @staticmethod
    def _relative_unique_files(paths: list[str], workspace_root: str) -> list[str]:
        seen: list[str] = []
        root = Path(workspace_root).expanduser().resolve()
        for raw_path in paths:
            if not raw_path:
                continue
            path = Path(raw_path)
            try:
                resolved = path.expanduser().resolve()
                relative = str(resolved.relative_to(root))
            except (OSError, ValueError):
                relative = str(path)
            if relative not in seen:
                seen.append(relative)
        return seen

    @staticmethod
    def _prompt_reference_terms(prompt: str) -> list[str]:
        terms: list[str] = []
        for term in re.findall(r"--[A-Za-z0-9][A-Za-z0-9_-]*", prompt):
            if term not in terms:
                terms.append(term)
        common = {
            "python",
            "pytest",
            "test",
            "tests",
            "file",
            "files",
            "cli",
            "project",
        }
        for term in re.findall(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]{2,}(?![A-Za-z0-9_])", prompt):
            lowered = term.lower()
            if "_" not in term and lowered in common:
                continue
            if term not in terms:
                terms.append(term)
        return terms

"""Handlers for parsed model responses that are not normal tool execution."""

from __future__ import annotations

from typing import Any

from allCode.agent.finalization_helpers import blocked_summary
from allCode.agent.inspect_summary import grounded_inspect_summary, has_inspect_summary_evidence
from allCode.agent.recovery import needs_validation_repair
from allCode.agent.round_runtime import RoundRuntime
from allCode.agent.round_runner_helpers import (
    evidence_answer,
    response_language,
    test_authoring_messages,
    validation_repair_messages,
    validated_complete,
)
from allCode.agent.round_text_response import RoundTextResponseHandler
from allCode.agent.turn_completion import LoopOutcome
from allCode.agent.validation_repair import validation_repair_needed
from allCode.core.models import Message, ToolCall, TurnInput, TurnState
from allCode.core.result import CompletionEvidence


class RoundResponseHandler:
    """Converts parser statuses into recovery prompts or loop outcomes."""

    def __init__(self, runner: Any) -> None:
        self._runner = runner
        self._text_handler = RoundTextResponseHandler(runner)

    async def handle(
        self,
        *,
        parsed,
        turn_input: TurnInput,
        state: TurnState,
        runtime: RoundRuntime,
        recovery,
        loop_guard,
        evidence: CompletionEvidence,
        routing,
        phase_gate,
        inspect_stage,
        more_mutation_before_validation: bool,
        round_index: int,
    ) -> LoopOutcome | None:
        if parsed.status == "empty_response":
            return await self._empty_response(state, runtime, recovery)
        if parsed.status == "reasoning_only":
            return await self._reasoning_only(
                turn_input,
                state,
                runtime,
                recovery,
                evidence,
                routing,
                phase_gate,
                inspect_stage,
                more_mutation_before_validation,
            )
        if parsed.status == "pseudo_tool_call":
            return self._pseudo_tool_call(parsed, runtime, routing)
        if parsed.status == "malformed_tool_call":
            return await self._malformed_tool_call(
                parsed,
                turn_input,
                state,
                runtime,
                recovery,
                loop_guard,
                evidence,
                routing,
                phase_gate,
                more_mutation_before_validation,
                round_index,
            )
        if parsed.status == "length_cutoff":
            await self._runner._record_recovery(
                state,
                recovery,
                "length_cutoff",
                attempts=1,
                last_error="model response hit length limit",
            )
            return LoopOutcome(status="partial", answer=parsed.text.rstrip(), error="length_cutoff")
        if parsed.text.strip():
            return await self._text_handler.handle(
                parsed=parsed,
                turn_input=turn_input,
                state=state,
                runtime=runtime,
                recovery=recovery,
                evidence=evidence,
                routing=routing,
                phase_gate=phase_gate,
                inspect_stage=inspect_stage,
                more_mutation_before_validation=more_mutation_before_validation,
            )
        return None

    async def _empty_response(self, state, runtime: RoundRuntime, recovery) -> LoopOutcome | None:
        if recovery.can_retry_empty_response():
            state.phase = "recovery"
            await self._runner._record_recovery(state, recovery, "empty_response", attempts=1)
            runtime.messages = self._runner._prompt_builder.empty_response_retry(runtime.messages)
            return None
        await self._runner._record_recovery(state, recovery, "empty_response", attempts=2, blocked=True)
        return LoopOutcome(status="failed", error="Model returned an empty response after retry.")

    async def _reasoning_only(
        self,
        turn_input: TurnInput,
        state,
        runtime: RoundRuntime,
        recovery,
        evidence: CompletionEvidence,
        routing,
        phase_gate,
        inspect_stage,
        more_mutation_before_validation: bool,
    ) -> LoopOutcome | None:
        if getattr(phase_gate, "phase", "") == "related_test_discovery_required":
            state.phase = "recovery"
            await self._runner._record_recovery(
                state,
                recovery,
                "no_progress",
                attempts=1,
                last_error="related test discovery is required before validation",
            )
            runtime.messages = self._runner._phase_block.related_test_discovery_messages(runtime.messages, evidence, phase_gate=phase_gate)
            return None
        if routing.requires_mutation and not evidence.has_resolution_evidence():
            if recovery.can_request_mutation_action():
                state.phase = "recovery"
                await self._runner._record_recovery(
                    state,
                    recovery,
                    "no_progress",
                    attempts=1,
                    last_error="model produced reasoning-only content before file mutation",
                )
                runtime.messages = self._runner._prompt_builder.mutation_action_request(runtime.messages)
                runtime.mutation_action_pending = True
                return None
        if more_mutation_before_validation:
            if recovery.can_request_mutation_action(max_attempts=6):
                state.phase = "recovery"
                await self._runner._record_recovery(
                    state,
                    recovery,
                    "no_progress",
                    attempts=recovery.mutation_action_requests,
                    last_error="test artifact is still required before final answer",
                )
                runtime.messages = test_authoring_messages(self._runner._phase_block, runtime.messages, evidence, phase_gate=phase_gate)
                runtime.mutation_action_pending = True
                return None
        if runtime.validation_action_pending and evidence.validation_passed is not True:
            if recovery.can_request_validation_action():
                state.phase = "recovery"
                await self._runner._record_recovery(
                    state,
                    recovery,
                    "validation_failed",
                    attempts=1,
                    last_error="file change exists but validation has not run",
                )
                runtime.messages = self._runner._prompt_builder.validation_action_request(runtime.messages)
                return None
            return LoopOutcome(
                status="partial",
                answer=blocked_summary(
                    self._runner._prompt_builder,
                    runtime.messages,
                    "validation_required_but_model_did_not_call_run_tests",
                ),
                error="Validation is required but the model did not call run_tests.",
            )
        if needs_validation_repair(routing, evidence) or validation_repair_needed(routing, evidence):
            if recovery.can_request_validation_repair():
                state.phase = "recovery"
                await self._runner._record_recovery(
                    state,
                    recovery,
                    "validation_failed",
                    attempts=recovery.validation_repair_requests,
                    last_error="model produced reasoning-only content after failed validation",
                )
                runtime.messages = validation_repair_messages(self._runner._phase_block, runtime.messages, evidence, phase_gate=phase_gate)
                runtime.validation_repair_pending = True
                runtime.mutation_action_pending = True
                return None
        if recovery.can_request_final_answer():
            state.phase = "recovery"
            await self._runner._record_recovery(state, recovery, "reasoning_only", attempts=1)
            if getattr(routing, "kind", "") == "inspect":
                runtime.messages = self._runner._prompt_builder.source_analysis_final_answer_request(
                    runtime.messages,
                    response_language=response_language(turn_input.user_prompt),
                )
            else:
                runtime.messages = self._runner._prompt_builder.final_answer_request(
                    runtime.messages,
                    response_language=response_language(turn_input.user_prompt),
                )
            return None
        await self._runner._record_recovery(state, recovery, "reasoning_only", attempts=2, blocked=True)
        if getattr(routing, "kind", "") == "inspect" and has_inspect_summary_evidence(evidence):
            return LoopOutcome(
                status="partial",
                answer=grounded_inspect_summary(
                    messages=runtime.messages,
                    evidence=evidence,
                    reason="model_returned_reasoning_only_after_retry",
                    response_language=response_language(turn_input.user_prompt),
                ),
                error="Model returned reasoning-only content after retry.",
            )
        return LoopOutcome(
            status="partial",
            answer=blocked_summary(self._runner._prompt_builder, runtime.messages, "model_returned_reasoning_only_after_retry"),
            error="Model returned reasoning-only content after retry.",
        )

    def _pseudo_tool_call(self, parsed, runtime: RoundRuntime, routing) -> LoopOutcome | None:
        if not runtime.pseudo_tool_retry_used:
            runtime.pseudo_tool_retry_used = True
            if parsed.text.strip():
                runtime.messages.append(Message(role="assistant", content=parsed.text.rstrip()))
            if getattr(routing, "read_only_requested", False):
                runtime.messages = self._runner._prompt_builder.natural_language_retry(runtime.messages)
            elif routing.allows_tool_use:
                runtime.messages = self._runner._prompt_builder.native_tool_call_retry(runtime.messages, parser_error=parsed.error)
                runtime.force_structured_tool_call = True
            else:
                runtime.messages = self._runner._prompt_builder.natural_language_retry(runtime.messages)
            return None
        return LoopOutcome(
            status="failed",
            answer=blocked_summary(self._runner._prompt_builder, runtime.messages, parsed.error or "pseudo_tool_call"),
            error=parsed.error or "Model emitted pseudo tool-call text after retry.",
        )

    async def _malformed_tool_call(
        self,
        parsed,
        turn_input,
        state,
        runtime: RoundRuntime,
        recovery,
        loop_guard,
        evidence: CompletionEvidence,
        routing,
        phase_gate,
        more_mutation_before_validation: bool,
        round_index: int,
    ) -> LoopOutcome | None:
        if routing.requires_mutation and more_mutation_before_validation and recovery.can_request_mutation_action(max_attempts=6):
            state.phase = "recovery"
            await self._runner._record_recovery(
                state,
                recovery,
                "no_progress",
                attempts=recovery.mutation_action_requests,
                last_error="malformed native tool call occurred before required artifact mutation",
            )
            if parsed.text.strip():
                runtime.messages.append(Message(role="assistant", content=parsed.text.rstrip()))
            runtime.messages = test_authoring_messages(self._runner._phase_block, runtime.messages, evidence, phase_gate=phase_gate)
            runtime.mutation_action_pending = True
            runtime.malformed_tool_retries = 0
            return None
        if routing.allows_tool_use and runtime.malformed_tool_retries < 4:
            runtime.malformed_tool_retries += 1
            state.phase = "recovery"
            await self._runner._record_recovery(
                state,
                recovery,
                "no_progress",
                attempts=runtime.malformed_tool_retries,
                last_error=f"malformed native tool call: {parsed.error or 'invalid arguments'}",
            )
            if parsed.text.strip():
                runtime.messages.append(Message(role="assistant", content=parsed.text.rstrip()))
            runtime.messages = self._runner._prompt_builder.native_tool_call_retry(runtime.messages, parser_error=parsed.error)
            runtime.force_structured_tool_call = True
            return None
        if routing.requires_validation and evidence.has_file_change():
            should_fallback = recovery.can_request_validation_action() or round_index >= self._runner._max_rounds - 2
            if should_fallback:
                outcome = await self._inject_validation_after_malformed(
                    turn_input,
                    state,
                    runtime,
                    recovery,
                    loop_guard,
                    evidence,
                    routing,
                    phase_gate,
                )
                if outcome is not None:
                    return outcome
                return None
        return LoopOutcome(
            status="failed",
            answer=blocked_summary(self._runner._prompt_builder, runtime.messages, parsed.error or "malformed_tool_call"),
            error=f"Model response could not be parsed safely: {parsed.error or 'malformed tool call'}",
        )

    async def _inject_validation_after_malformed(
        self,
        turn_input,
        state,
        runtime: RoundRuntime,
        recovery,
        loop_guard,
        evidence: CompletionEvidence,
        routing,
        phase_gate,
    ) -> LoopOutcome | None:
        state.phase = "tools"
        await self._runner._record_recovery(
            state,
            recovery,
            "validation_failed",
            attempts=1,
            last_error="validation fallback injected after malformed tool calls",
        )
        validation_results = await self._runner._execute_validation_fallback(
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
        runtime.messages = self._runner._prompt_builder.append_tool_results(runtime.messages, validation_results)
        runtime.validation_action_pending = False
        runtime.awaiting_revalidation_after_mutation = False
        if validated_complete(routing, evidence):
            return LoopOutcome(
                status="success",
                answer=evidence_answer(turn_input.user_prompt, evidence, turn_input.workspace.root),
            )
        if any(result.name == "run_tests" and result.metadata.get("validation_passed") is False for result in validation_results):
            runtime.validation_repair_pending = True
            runtime.mutation_action_pending = True
            runtime.mutation_attempted_after_failed_validation = False
            runtime.mutation_succeeded_after_failed_validation = False
            runtime.malformed_tool_retries = 0
        return None

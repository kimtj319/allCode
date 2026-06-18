"""Handler for normal tool-call rounds."""

from __future__ import annotations

from typing import Any

from allCode.agent.finalization_helpers import blocked_summary, has_blocking_tool_result
from allCode.agent.grounding import next_candidate_read_call, next_representative_source_probe_call
from allCode.agent.phase_gate import mutation_artifact_required
from allCode.agent.round_runtime import INSPECTION_TOOL_NAMES, MUTATION_TOOL_NAMES, RoundRuntime
from allCode.agent.round_runner_helpers import (
    can_retry_phase_block,
    evidence_answer,
    mutation_complete,
    phase_block_feedback,
    record_context_reads,
    response_language,
    test_authoring_messages,
    validation_repair_messages,
    validated_complete,
)
from allCode.agent.turn_completion import LoopOutcome
from allCode.core.models import Message, ToolCall, TurnInput, TurnState
from allCode.core.result import CompletionEvidence


class RoundToolHandler:
    """Updates loop state after model-selected tools execute."""

    def __init__(self, runner: Any) -> None:
        self._runner = runner

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
        allowed_tool_names: set[str],
        round_index: int,
    ) -> LoopOutcome | None:
        state.phase = "tools"
        results = await self._runner._tool_call_processor.execute(
            turn_input,
            state,
            parsed.tool_calls,
            loop_guard,
            recovery,
            evidence,
            routing,
            allowed_tool_names=allowed_tool_names,
            phase_gate=phase_gate,
            inspect_stage=inspect_stage,
        )
        runtime.messages.append(Message(role="assistant", content=parsed.text, tool_calls=parsed.tool_calls))
        runtime.messages = self._runner._prompt_builder.append_tool_results(runtime.messages, results)
        record_context_reads(
            results,
            runtime.repair_context_read_paths,
            workspace_root=turn_input.workspace.root,
        )
        if any(result.ok and result.name in {*MUTATION_TOOL_NAMES, "run_tests"} for result in results):
            runtime.phase_block_counts.clear()
        self._record_inspection_counts(runtime, results)
        await self._record_mutation_and_validation_state(
            turn_input,
            state,
            runtime,
            recovery,
            loop_guard,
            evidence,
            routing,
            phase_gate,
            results,
            round_index,
        )
        if validated_complete(routing, evidence):
            # Give the model one tool-free round to write the actual final
            # answer (e.g. explaining *why* validation had failed, or the summary
            # the user asked for) before falling back to the deterministic
            # evidence template — otherwise a validation-passing turn always
            # returns the terse "작업을 완료했습니다 …" stub and never addresses a
            # request to explain or summarize. Mirrors the mutation_complete path.
            if runtime.final_answer_after_change_requested:
                return LoopOutcome(
                    status="success",
                    answer=evidence_answer(turn_input.user_prompt, evidence, turn_input.workspace.root),
                )
            runtime.final_answer_after_change_requested = True
            runtime.messages = self._runner._prompt_builder.final_answer_request(
                runtime.messages,
                response_language=response_language(turn_input.user_prompt),
            )
            return None
        if mutation_complete(routing, evidence):
            if runtime.final_answer_after_change_requested:
                return LoopOutcome(
                    status="success",
                    answer=evidence_answer(turn_input.user_prompt, evidence, turn_input.workspace.root),
                )
            runtime.final_answer_after_change_requested = True
            runtime.messages = self._runner._prompt_builder.final_answer_request(
                runtime.messages,
                response_language=response_language(turn_input.user_prompt),
            )
            return None
        phase_block = await self._handle_phase_block(runtime, recovery, state, evidence, phase_gate, results)
        if phase_block is not None:
            return phase_block
        patch_block = await self._handle_patch_strategy(runtime, recovery, state, evidence, phase_gate, results)
        if patch_block is not None:
            return patch_block
        grounding = await self._handle_grounding(turn_input, state, runtime, recovery, loop_guard, evidence, routing, phase_gate)
        if grounding is not None:
            return grounding
        if any(result.is_final and result.ok for result in results):
            return LoopOutcome(status="success", answer=next(result.content for result in results if result.is_final and result.ok))
        if has_blocking_tool_result(results):
            # Graceful degradation on a read/inspect loop: instead of failing the
            # turn with the raw loop-guard block dump, answer from the evidence
            # already gathered. Switch to a tools-suppressed final-answer round
            # (no more tool calls → no further loop). Only for non-mutation turns
            # (a blocked mutation turn must not "complete" without its change),
            # and only once (the flag guards against re-entry).
            if not getattr(routing, "requires_mutation", False) and not runtime.inspect_final_answer_requested:
                runtime.inspect_final_answer_requested = True
                runtime.messages = self._runner._prompt_builder.final_answer_request(
                    runtime.messages,
                    response_language=response_language(turn_input.user_prompt),
                )
                return None
            return LoopOutcome(
                status="partial",
                answer=blocked_summary(self._runner._prompt_builder, runtime.messages, "tool_progress_blocked"),
                error="Tool progress blocked by loop guard.",
            )
        if (
            routing.requires_mutation
            and not evidence.has_resolution_evidence()
            and any(result.name == "read_file" and result.ok for result in results)
            and recovery.can_request_mutation_action()
        ):
            state.phase = "recovery"
            await self._runner._record_recovery(
                state,
                recovery,
                "no_progress",
                attempts=1,
                last_error="target inspected but no mutation has run",
            )
            runtime.messages = self._runner._prompt_builder.mutation_action_request(runtime.messages)
            runtime.mutation_action_pending = True
        return None

    @staticmethod
    def _record_inspection_counts(runtime: RoundRuntime, results) -> None:
        inspection_count = sum(1 for result in results if result.name in INSPECTION_TOOL_NAMES)
        if inspection_count:
            runtime.inspection_actions += inspection_count
            if not any(result.name in MUTATION_TOOL_NAMES and result.ok for result in results):
                runtime.inspection_rounds += 1

    async def _record_mutation_and_validation_state(
        self,
        turn_input,
        state,
        runtime: RoundRuntime,
        recovery,
        loop_guard,
        evidence: CompletionEvidence,
        routing,
        phase_gate,
        results,
        round_index: int,
    ) -> None:
        had_failed_validation = evidence.validation_passed is False
        mutation_results = [result for result in results if result.name in MUTATION_TOOL_NAMES]
        if had_failed_validation and mutation_results:
            runtime.mutation_attempted_after_failed_validation = True
            runtime.mutation_succeeded_after_failed_validation = any(result.ok for result in mutation_results)
        if any(result.ok and result.name in MUTATION_TOOL_NAMES for result in results):
            more_mutation = mutation_artifact_required(
                turn_input.user_prompt,
                evidence,
                workspace_root=turn_input.workspace.root,
                routing=routing,
            )
            runtime.mutation_action_pending = more_mutation
            runtime.validation_repair_pending = False
            runtime.awaiting_revalidation_after_mutation = (
                had_failed_validation
                and routing.requires_validation
                and evidence.validation_passed is not True
                and not more_mutation
            )
            runtime.validation_action_pending = (
                routing.requires_validation
                and evidence.validation_passed is not True
                and not more_mutation
                and not runtime.awaiting_revalidation_after_mutation
            )
            if self._runner._should_inject_validation_action(
                round_index,
                routing,
                evidence,
                recovery,
                validation_action_pending=runtime.validation_action_pending,
                awaiting_revalidation_after_mutation=runtime.awaiting_revalidation_after_mutation,
            ):
                await self._inject_validation(turn_input, state, runtime, recovery, loop_guard, evidence, routing, phase_gate)
        if any(result.name == "run_tests" for result in results):
            runtime.awaiting_revalidation_after_mutation = False
            runtime.validation_action_pending = False
        if any(result.name == "run_tests" and result.metadata.get("validation_passed") is False for result in results):
            runtime.validation_repair_pending = True
            runtime.mutation_action_pending = True
            runtime.validation_action_pending = False
            runtime.mutation_attempted_after_failed_validation = False
            runtime.mutation_succeeded_after_failed_validation = False

    async def _inject_validation(self, turn_input, state, runtime, recovery, loop_guard, evidence, routing, phase_gate) -> None:
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
        if any(result.name == "run_tests" and result.metadata.get("validation_passed") is False for result in validation_results):
            runtime.validation_repair_pending = True
            runtime.mutation_action_pending = True
            runtime.mutation_attempted_after_failed_validation = False
            runtime.mutation_succeeded_after_failed_validation = False

    async def _handle_phase_block(self, runtime, recovery, state, evidence, phase_gate, results) -> LoopOutcome | None:
        blocked_phases = {
            "mutation_required",
            "test_authoring_required",
            "related_test_discovery_required",
            "repair_mutation_required",
            "validation_failed",
        }
        if not (results and all(result.error_type == "schema_denied" for result in results) and phase_gate.phase in blocked_phases):
            return None
        block_reason = phase_block_feedback(phase_gate, results)
        if not can_retry_phase_block(runtime.phase_block_counts, phase_gate=phase_gate, reason="schema_denied"):
            return LoopOutcome(
                status="partial",
                answer=blocked_summary(self._runner._prompt_builder, runtime.messages, block_reason),
                error=f"Phase block retry budget exhausted: {block_reason}",
            )
        state.phase = "recovery"
        await self._runner._record_recovery(state, recovery, "no_progress", attempts=recovery.mutation_action_requests, last_error=block_reason)
        if phase_gate.phase == "test_authoring_required":
            runtime.messages = test_authoring_messages(self._runner._phase_block, runtime.messages, evidence, phase_gate=phase_gate, phase_block_reason=block_reason)
        elif phase_gate.phase == "related_test_discovery_required":
            runtime.messages = self._runner._phase_block.related_test_discovery_messages(runtime.messages, evidence, phase_gate=phase_gate, phase_block_reason=block_reason)
        elif phase_gate.phase in {"validation_failed", "repair_mutation_required"}:
            runtime.messages = validation_repair_messages(self._runner._phase_block, runtime.messages, evidence, phase_gate=phase_gate, phase_block_reason=block_reason)
            runtime.validation_repair_pending = True
        elif recovery.can_request_mutation_action(max_attempts=6):
            runtime.messages = test_authoring_messages(self._runner._phase_block, runtime.messages, evidence, phase_gate=phase_gate)
        else:
            return LoopOutcome(
                status="partial",
                answer=blocked_summary(self._runner._prompt_builder, runtime.messages, "mutation_action_retry_budget_exhausted"),
                error="Mutation action retry budget exhausted.",
            )
        runtime.mutation_action_pending = True
        return None

    async def _handle_patch_strategy(self, runtime, recovery, state, evidence, phase_gate, results) -> LoopOutcome | None:
        if not any(result.error_type == "patch_strategy_required" for result in results):
            return None
        block_reason = phase_block_feedback(phase_gate, results)
        if not can_retry_phase_block(runtime.phase_block_counts, phase_gate=phase_gate, reason="patch_strategy_required"):
            return LoopOutcome(
                status="partial",
                answer=blocked_summary(self._runner._prompt_builder, runtime.messages, block_reason),
                error=f"Patch strategy retry budget exhausted: {block_reason}",
            )
        state.phase = "recovery"
        await self._runner._record_recovery(
            state,
            recovery,
            "no_progress",
            attempts=runtime.phase_block_counts.get((phase_gate.phase, "patch_strategy_required"), 1),
            last_error=block_reason,
        )
        runtime.messages = validation_repair_messages(self._runner._phase_block, runtime.messages, evidence, phase_gate=phase_gate, phase_block_reason=block_reason)
        runtime.validation_repair_pending = True
        runtime.mutation_action_pending = True
        return None

    async def _handle_grounding(self, turn_input, state, runtime, recovery, loop_guard, evidence, routing, phase_gate) -> LoopOutcome | None:
        action_budget = self._runner._effective_inspect_action_budget(turn_input.user_prompt, routing, evidence)
        remaining_budget = max(0, action_budget - runtime.inspection_actions)
        if remaining_budget <= 0:
            return None
        grounding_call = next_candidate_read_call(evidence, workspace_root=turn_input.workspace.root)
        if grounding_call is None and getattr(routing, "kind", "") == "inspect" and getattr(routing, "read_only_requested", False):
            grounding_call = next_representative_source_probe_call(
                evidence,
                workspace_root=turn_input.workspace.root,
                remaining_budget=remaining_budget,
            )
        if grounding_call is None:
            return None
        grounding_results = await self._runner._tool_call_processor.execute(
            turn_input,
            state,
            [grounding_call],
            loop_guard,
            recovery,
            evidence,
            routing,
            allowed_tool_names={grounding_call.name},
            phase_gate=phase_gate,
        )
        runtime.messages.append(Message(role="assistant", content="", tool_calls=[grounding_call]))
        runtime.messages = self._runner._prompt_builder.append_tool_results(runtime.messages, grounding_results)
        runtime.inspection_actions += sum(1 for result in grounding_results if result.name in INSPECTION_TOOL_NAMES)
        return None

"""Model round execution and recovery orchestration."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.agent.finalization_helpers import blocked_summary
from allCode.agent.grounding import grounding_required
from allCode.agent.inspect_staging import decide_inspect_stage
from allCode.agent.language import ResponseLanguage, detect_response_language
from allCode.agent.phase_block import PhaseBlockHelper
from allCode.agent.phase_gate import build_phase_tool_gate, mutation_artifact_required
from allCode.agent.prompt_builder import PromptBuilder
from allCode.agent.recovery import RecoveryTracker, ToolLoopGuard
from allCode.agent.revalidation import RevalidationOrchestrator, evidence_final_answer, mutation_change_complete, validated_change_complete
from allCode.agent.round_events import publish_model_request, publish_parsed_response
from allCode.agent.round_context import record_repair_context_reads
from allCode.agent.round_response_handler import RoundResponseHandler
from allCode.agent.round_runtime import RoundRuntime
from allCode.agent.round_state import RoundStateSnapshot
from allCode.agent.round_tool_handler import RoundToolHandler
from allCode.agent.stream_collector import ModelStreamCollector
from allCode.agent.tool_call_processor import ToolCallProcessor
from allCode.agent.turn_completion import LoopOutcome
from allCode.agent.validation_controller import ValidationRepairController
from allCode.agent.validation_repair import validation_repair_needed
from allCode.core.event_bus import EventBus
from allCode.core.events import (
    InspectFinalizationGateOpened,
    InspectStageSelected,
    ModelStreamStarted,
    PhaseTransitioned,
    RecoveryStateUpdated,
    RepairAttemptExhausted,
    ValidationActionInjected,
)
from allCode.core.models import Message, ToolCall, ToolResult, TurnInput, TurnState
from allCode.core.result import CompletionEvidence
from allCode.llm.response_parser import ResponseParser


class RoundRunner:
    """Runs model/tool rounds while delegating focused sub-responsibilities."""

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
        self._phase_block = PhaseBlockHelper(prompt_builder)
        self._revalidation = RevalidationOrchestrator(tool_call_processor=tool_call_processor, max_rounds=max_rounds)
        self._response_handler = RoundResponseHandler(self)
        self._tool_handler = RoundToolHandler(self)

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
        runtime = RoundRuntime(messages=list(state.messages), mutation_action_pending=force_mutation_action)
        completion_evidence.grounding_required = grounding_required(turn_input.user_prompt, routing)

        for round_index in range(self._max_rounds):
            state.phase = "model"
            more_mutation = self._update_repair_flags(turn_input, routing, completion_evidence, runtime)
            control = self._validation_controller.decide(
                snapshot=self._snapshot(round_index, completion_evidence, recovery, runtime),
                routing=routing,
                evidence=completion_evidence,
                validation_action_pending=runtime.validation_action_pending,
                validation_repair_pending=runtime.validation_repair_pending,
                mutation_action_pending=runtime.mutation_action_pending,
                awaiting_revalidation_after_mutation=runtime.awaiting_revalidation_after_mutation,
                more_mutation_before_validation=more_mutation,
                validation_action_requested=recovery.validation_action_requested,
                max_rounds=self._max_rounds,
            )
            exhausted = await self._apply_validation_control(state, control, runtime)
            if exhausted is not None:
                state.messages = runtime.messages
                return exhausted

            inspection_budget_available = self._inspection_budget_available(runtime.inspection_actions, runtime.inspection_rounds)
            lock_to_mutation = runtime.mutation_action_pending and (
                not runtime.validation_repair_pending
                and (not inspection_budget_available or recovery.mutation_action_requests >= 2)
            )
            phase_gate = build_phase_tool_gate(
                prompt=turn_input.user_prompt,
                routing=routing,
                evidence=completion_evidence,
                workspace_root=turn_input.workspace.root,
                inspection_budget_available=inspection_budget_available,
                mutation_action_pending=lock_to_mutation,
                validation_action_pending=runtime.validation_action_pending,
                validation_repair_pending=runtime.validation_repair_pending,
                awaiting_revalidation_after_mutation=runtime.awaiting_revalidation_after_mutation,
                repair_context_read_paths=runtime.repair_context_read_paths,
                test_authoring_inspection_rounds=runtime.inspection_rounds,
            )
            inspect_stage = decide_inspect_stage(
                prompt=turn_input.user_prompt,
                routing=routing,
                evidence=completion_evidence,
                round_index=round_index,
                inspect_round_budget=self._inspect_round_budget,
                final_answer_requested=runtime.inspect_final_answer_requested,
            )
            if inspect_stage.active and runtime.last_inspect_stage != inspect_stage.stage:
                runtime.last_inspect_stage = inspect_stage.stage
                if inspect_stage.stage in {"source_discovery", "targeted_read"}:
                    runtime.messages = self._prompt_builder.inspect_stage_request(
                        runtime.messages,
                        stage=inspect_stage.stage,
                        target_paths=inspect_stage.target_paths,
                        reason=inspect_stage.reason,
                    )
                await self._publish(
                    InspectStageSelected(
                        turn_id=state.turn_id,
                        message=f"Inspect stage selected: {inspect_stage.stage}.",
                        data={
                            "round": round_index + 1,
                            "stage": inspect_stage.stage,
                            "reason": inspect_stage.reason,
                            "allowed_tools": sorted(inspect_stage.allowed_tool_names),
                            "target_paths": list(inspect_stage.target_paths),
                            "evidence_complete": inspect_stage.evidence_complete,
                        },
                    )
                )
            if (
                inspect_stage.stage == "finalize"
                and not runtime.inspect_final_answer_requested
                and completion_evidence.inspect_observation_count > 0
            ):
                runtime.inspect_final_answer_requested = True
                await self._publish(
                    InspectFinalizationGateOpened(
                        turn_id=state.turn_id,
                        message="Inspect finalization gate opened.",
                        data={
                            "round": round_index + 1,
                            "reason": inspect_stage.reason,
                            "source_overview_paths": list(completion_evidence.source_overview_paths),
                            "inspected_paths": list(completion_evidence.inspected_paths),
                            "search_candidate_paths": list(completion_evidence.search_candidate_paths[:5]),
                        },
                    )
                )
                runtime.messages = self._prompt_builder.final_answer_request(
                    runtime.messages,
                    response_language=self._response_language(turn_input.user_prompt),
                )
            injected = await self._maybe_inject_validation(
                turn_input,
                state,
                runtime,
                loop_guard,
                recovery,
                completion_evidence,
                routing,
                phase_gate,
                round_index,
                control,
            )
            if injected is not None:
                state.messages = runtime.messages
                return injected
            if control.should_inject_validation_action:
                continue

            suppress_tools_for_final_answer = (
                runtime.inspect_final_answer_requested
                or (
                    runtime.final_answer_after_change_requested
                    and self._mutation_change_complete(routing, completion_evidence)
                )
            )
            allowed_only = None
            if suppress_tools_for_final_answer:
                allowed_only = set()
            elif phase_gate.active:
                allowed_only = phase_gate.allowed_tool_names
            elif inspect_stage.active:
                allowed_only = inspect_stage.allowed_tool_names
            tool_schemas = self._tool_call_processor.tool_schemas_for_routing(
                routing,
                suppress_validation=runtime.validation_repair_pending,
                only_mutation=lock_to_mutation,
                only_validation=runtime.validation_action_pending,
                include_validation_probe=(
                    lock_to_mutation and routing.requires_validation and not completion_evidence.validation_commands
                ),
                allowed_only=allowed_only,
            )
            if (
                phase_gate.active
                and not tool_schemas
                and phase_gate.phase in {"validation_failed", "repair_mutation_required"}
                and phase_gate.allowed_tool_names == {"read_file"}
            ):
                phase_gate = phase_gate.model_copy(
                    update={
                        "allowed_tool_names": {"patch_file", "write_file"},
                        "required_next_action": "Apply the validation repair with patch_file or write_file.",
                        "reason": f"{phase_gate.reason}; read_file is unavailable in the current registry",
                        "preferred_next_tools": ["patch_file", "write_file"],
                    }
                )
                tool_schemas = self._tool_call_processor.tool_schemas_for_routing(
                    routing,
                    suppress_validation=runtime.validation_repair_pending,
                    allowed_only=phase_gate.allowed_tool_names,
                )
            allowed_tool_names = {schema.name for schema in tool_schemas}
            await publish_model_request(
                self._event_bus,
                state=state,
                runtime=runtime,
                routing=routing,
                phase_gate=phase_gate,
                allowed_tool_names=allowed_tool_names,
                round_index=round_index,
            )

            has_tool_results = any(message.role == "tool" for message in runtime.messages)
            stream_phase = "continuation" if has_tool_results else ("retry" if recovery.states else "initial")
            await self._publish(
                ModelStreamStarted(
                    turn_id=state.turn_id,
                    message=f"Model stream started for round {round_index + 1}.",
                    data={"round": round_index + 1, "retry": stream_phase == "retry", "stream_phase": stream_phase},
                )
            )
            events, stream_timed_out = await self._stream_collector.collect(
                state=state,
                messages=runtime.messages,
                recovery=recovery,
                tool_schemas=tool_schemas,
                stream_text=not (routing.requires_external_knowledge and not has_tool_results),
            )
            if stream_timed_out and not events and recovery.can_retry_stream_timeout():
                state.phase = "recovery"
                runtime.messages = self._prompt_builder.empty_response_retry(runtime.messages)
                continue
            if stream_timed_out and not events:
                return LoopOutcome(status="failed", error="Model stream timed out without usable output.")

            parsed = self._parser.parse_events(events)
            await publish_parsed_response(
                self._event_bus,
                state=state,
                parsed=parsed,
                runtime=runtime,
                round_index=round_index,
            )
            if parsed.usage is not None:
                state.token_usage = parsed.usage

            if parsed.status == "ok_tool_calls":
                if runtime.final_answer_after_change_requested and self._mutation_change_complete(routing, completion_evidence):
                    return LoopOutcome(
                        status="success",
                        answer=self._evidence_final_answer(turn_input.user_prompt, completion_evidence, turn_input.workspace.root),
                    )
                outcome = await self._tool_handler.handle(
                    parsed=parsed,
                    turn_input=turn_input,
                    state=state,
                    runtime=runtime,
                    recovery=recovery,
                    loop_guard=loop_guard,
                    evidence=completion_evidence,
                    routing=routing,
                    phase_gate=phase_gate,
                    inspect_stage=inspect_stage,
                    allowed_tool_names=allowed_tool_names,
                    round_index=round_index,
                )
            else:
                outcome = await self._response_handler.handle(
                    parsed=parsed,
                    turn_input=turn_input,
                    state=state,
                    runtime=runtime,
                    recovery=recovery,
                    loop_guard=loop_guard,
                    evidence=completion_evidence,
                    routing=routing,
                    phase_gate=phase_gate,
                    more_mutation_before_validation=more_mutation,
                    round_index=round_index,
                )
            state.messages = runtime.messages
            if outcome is not None:
                return outcome

        state.messages = runtime.messages
        return LoopOutcome(
            status="partial",
            answer=blocked_summary(self._prompt_builder, runtime.messages, "max_rounds_reached"),
            error="The turn reached the maximum number of model rounds before a final answer was produced.",
        )

    def _update_repair_flags(
        self,
        turn_input: TurnInput,
        routing,
        evidence: CompletionEvidence,
        runtime: RoundRuntime,
    ) -> bool:
        more_mutation = mutation_artifact_required(
            turn_input.user_prompt,
            evidence,
            workspace_root=turn_input.workspace.root,
            routing=routing,
        )
        if evidence.validation_passed is True:
            runtime.validation_action_pending = False
        if runtime.validation_action_pending or runtime.awaiting_revalidation_after_mutation:
            runtime.validation_repair_pending = False
        else:
            runtime.validation_repair_pending = runtime.validation_repair_pending or validation_repair_needed(routing, evidence)
        return more_mutation

    @staticmethod
    def _snapshot(
        round_index: int,
        evidence: CompletionEvidence,
        recovery: RecoveryTracker,
        runtime: RoundRuntime,
    ) -> RoundStateSnapshot:
        return RoundStateSnapshot(
            round_index=round_index,
            phase="normal",
            mutation_since_last_validation=evidence.has_file_change() and evidence.validation_passed is not True,
            validation_attempts=len(evidence.validation_commands),
            repair_attempts=recovery.validation_repair_requests,
            last_validation_status=evidence.validation_passed,
            mutation_attempted_after_failed_validation=runtime.mutation_attempted_after_failed_validation,
            mutation_succeeded_after_failed_validation=runtime.mutation_succeeded_after_failed_validation,
            last_validation_failure_symbols=list(evidence.validation_failure_symbols),
        )

    async def _apply_validation_control(self, state: TurnState, control, runtime: RoundRuntime) -> LoopOutcome | None:
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
                answer=blocked_summary(self._prompt_builder, runtime.messages, "validation_repair_attempts_exhausted"),
                error="Validation repair attempts are exhausted.",
            )
        runtime.validation_action_pending = control.validation_action_pending
        runtime.validation_repair_pending = control.validation_repair_pending
        runtime.mutation_action_pending = runtime.mutation_action_pending or control.mutation_action_pending
        runtime.awaiting_revalidation_after_mutation = control.awaiting_revalidation_after_mutation
        if control.phase != "normal":
            await self._publish(
                PhaseTransitioned(
                    turn_id=state.turn_id,
                    message=f"Round phase transitioned: {control.phase}.",
                    data=control.model_dump(mode="json"),
                )
            )
        return None

    async def _maybe_inject_validation(
        self,
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
        should_inject = control.should_inject_validation_action or self._should_inject_validation_action(
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
            evidence,
            routing,
            phase_gate=phase_gate,
        )
        validation_call = ToolCall(id=validation_results[0].call_id, name="run_tests", arguments={})
        runtime.messages.append(Message(role="assistant", content="", tool_calls=[validation_call]))
        runtime.messages = self._prompt_builder.append_tool_results(runtime.messages, validation_results)
        runtime.validation_action_pending = False
        runtime.awaiting_revalidation_after_mutation = False
        if any(result.name == "run_tests" and result.metadata.get("validation_passed") is False for result in validation_results):
            runtime.validation_repair_pending = True
            runtime.mutation_action_pending = True
            runtime.mutation_attempted_after_failed_validation = False
            runtime.mutation_succeeded_after_failed_validation = False
        if self._validated_change_complete(routing, evidence):
            return LoopOutcome(status="success", answer=self._evidence_final_answer(turn_input.user_prompt, evidence, turn_input.workspace.root))
        return None

    def _test_authoring_messages(self, messages: list[Message], evidence: CompletionEvidence, *, phase_gate, phase_block_reason: str = "") -> list[Message]:
        return self._phase_block.test_authoring_messages(messages, evidence, phase_gate=phase_gate, phase_block_reason=phase_block_reason)
    def _validation_repair_messages(self, messages: list[Message], evidence: CompletionEvidence, *, phase_gate, phase_block_reason: str = "") -> list[Message]:
        return self._phase_block.validation_repair_messages(messages, evidence, phase_gate=phase_gate, phase_block_reason=phase_block_reason)
    def _can_retry_phase_block(self, counts: dict[tuple[str, str], int], *, phase_gate, reason: str, max_attempts: int = 2) -> bool:
        return PhaseBlockHelper.can_retry(counts, phase_gate=phase_gate, reason=reason, max_attempts=max_attempts)
    def _phase_block_feedback(self, phase_gate, results: Sequence[ToolResult]) -> str:
        return PhaseBlockHelper.feedback(phase_gate, results)
    def _record_repair_context_reads(self, results: Sequence[ToolResult], repair_context_read_paths: set[str], *, workspace_root: str) -> None:
        record_repair_context_reads(results, repair_context_read_paths, workspace_root=workspace_root)
    async def _record_recovery(self, state: TurnState, recovery: RecoveryTracker, reason, *, attempts: int = 0, last_error: str | None = None, blocked: bool = False) -> None:
        recovery.add_state(reason, attempts=attempts, last_error=last_error, blocked=blocked)
        latest = recovery.states[-1]
        await self._publish(RecoveryStateUpdated(turn_id=state.turn_id, message=f"Recovery state updated: {latest.reason}.", data=latest.model_dump(mode="json")))
    async def _publish(self, event) -> None:
        await self._event_bus.publish(event)
    def _inspection_budget_available(self, inspection_actions: int, inspection_rounds: int) -> bool:
        return inspection_actions < self._inspect_action_budget and inspection_rounds < self._inspect_round_budget
    def _should_inject_validation_action(self, round_index: int, routing, evidence: CompletionEvidence, recovery: RecoveryTracker, *, validation_action_pending: bool, awaiting_revalidation_after_mutation: bool) -> bool:
        return self._revalidation.should_inject(round_index, routing, evidence, recovery, validation_action_pending=validation_action_pending, awaiting_revalidation_after_mutation=awaiting_revalidation_after_mutation)
    async def _execute_validation_fallback(self, turn_input: TurnInput, state: TurnState, loop_guard: ToolLoopGuard, recovery: RecoveryTracker, completion_evidence: CompletionEvidence, routing, *, phase_gate) -> list[ToolResult]:
        return await self._revalidation.execute(turn_input, state, loop_guard, recovery, completion_evidence, routing, phase_gate=phase_gate)
    @staticmethod
    def _validated_change_complete(routing, evidence: CompletionEvidence) -> bool:
        return validated_change_complete(routing, evidence)
    @staticmethod
    def _mutation_change_complete(routing, evidence: CompletionEvidence) -> bool:
        return mutation_change_complete(routing, evidence)
    @staticmethod
    def _evidence_final_answer(prompt: str, evidence: CompletionEvidence, workspace_root: str) -> str:
        return evidence_final_answer(prompt, evidence, workspace_root)

    @staticmethod
    def _response_language(prompt: str) -> ResponseLanguage:
        return detect_response_language(prompt)

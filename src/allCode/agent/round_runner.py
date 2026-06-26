"""Model round execution and recovery orchestration."""

from __future__ import annotations

from allCode.agent.finalization_helpers import blocked_summary
from allCode.agent.context_condensation import condense_messages_for_model, window_aware_max_chars
from allCode.agent.final_answer_context import final_answer_call_messages
from allCode.agent.grounding import grounding_required
from allCode.agent.phase_block import PhaseBlockHelper
from allCode.agent.phase_gate import build_phase_tool_gate
from allCode.agent.prompt_builder import PromptBuilder
from allCode.agent.recovery import RecoveryTracker, ToolLoopGuard
from allCode.agent.revalidation import RevalidationOrchestrator
from allCode.agent.round_events import publish_model_request, publish_parsed_response
from allCode.agent.round_inspect_flow import apply_inspect_stage
from allCode.agent.round_inspection_budget import (
    effective_inspect_action_budget,
    effective_inspect_round_budget,
    inspection_budget_available,
)
from allCode.agent.inspect_summary import grounded_inspect_summary, has_inspect_summary_evidence
from allCode.agent.modify_fallback import has_modify_plan_evidence, modify_change_plan_fallback
from allCode.agent.round_repair_state import round_state_snapshot, update_repair_flags
from allCode.agent.round_response_handler import RoundResponseHandler
from allCode.agent.round_runtime import RoundRuntime
from allCode.agent.round_tool_handler import RoundToolHandler
from allCode.agent.round_runner_helpers import evidence_answer, mutation_complete, response_language
from allCode.agent.round_validation import apply_validation_control, maybe_inject_validation
from allCode.agent.stream_collector import ModelStreamCollector
from allCode.agent.source_final_brief import source_final_evidence_brief
from allCode.agent.task_loop_digest import build_task_loop_digest, task_loop_digest_messages
from allCode.agent.tool_call_processor import ToolCallProcessor
from allCode.agent.turn_completion import LoopOutcome
from allCode.agent.validation_controller import ValidationRepairController
from allCode.agent.web_finalization import (
    should_request_web_final_answer,
    web_evidence_fallback_answer,
)
from allCode.core.event_bus import EventBus
from allCode.core.events import ModelStreamStarted, RecoveryStateUpdated, UserPromptSubmitted
from allCode.core.models import Message, ToolResult, TurnInput, TurnState
from allCode.core.result import CompletionEvidence
from allCode.llm.response_parser import ResponseParser


class RoundRunner:
    """Runs model/tool rounds while delegating focused sub-responsibilities."""

    def __init__(
        self,
        *,
        llm_client=None,
        settings=None,
        implementation_settings=None,
        event_bus: EventBus,
        prompt_builder: PromptBuilder,
        tool_call_processor: ToolCallProcessor,
        stream_collector: ModelStreamCollector,
        max_rounds: int = 12,
        # Multi-file, cross-cutting changes need to read several layers (config ->
        # store -> service -> cli) before editing, so give the loop enough
        # inspection room before it locks to mutation-only.
        inspect_action_budget: int = 7,
        inspect_round_budget: int = 6,
        steering=None,
        unified_loop: bool = False,
    ) -> None:
        # Optional SteeringQueue: drained at each round boundary so user
        # guidance typed mid-turn is fed into the next model round.
        self._steering = steering
        self._unified = unified_loop
        self._settings = settings
        # Higher-tier model used for code-implementation (mutation) turns. Falls
        # back to the base model when unset or identically named, so an unset or
        # equal implementation_model_name means a single model is used throughout.
        self._implementation_settings = implementation_settings or settings
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

    def _turn_settings(self, routing) -> "object":
        """Model settings for this turn: the implementation (higher) tier when the
        turn actually implements code (a mutation/modify route), else the base
        tier used for planning, inspection, answers, and other reasoning.

        When implementation_model_name is unset or equal to model_name, the
        implementation settings resolve to the base settings, so the same model is
        used either way."""
        caps = set(getattr(routing, "tool_capabilities", set()) or set())
        implements_code = bool(
            getattr(routing, "requires_mutation", False)
            or getattr(routing, "kind", "") == "modify"
            or caps.intersection({"mutate_file", "delete_file"})
        )
        # getattr fallbacks keep partially-constructed runners (e.g. tests using
        # object.__new__) working: when settings are absent this returns None and
        # the stream collector falls back to its own configured model.
        base = getattr(self, "_settings", None)
        impl = getattr(self, "_implementation_settings", None) or base
        # NOTE: auto-routing reasoning_effort="high" on modify/inspect turns was
        # tried and MEASURED to REGRESS gpt-oss agentic reliability (a 100-prompt
        # codex comparison dropped 75%->62% harness parity, with new
        # pseudo-tool-call / raw-tool-blob / abort failure modes concentrated in
        # exactly the high-effort turns). High reasoning effort makes gpt-oss more
        # likely to emit tool intent as floating text instead of a structured
        # call. Effort is therefore left to the configured value (opt-in via
        # config.model.reasoning_effort), not forced per route.
        return impl if implements_code else base

    async def _plan_final_answer(self, state: TurnState, runtime, recovery, turn_settings) -> str:
        """Plan mode: make one tool-suppressed model call so the model writes the
        implementation plan from what it gathered, instead of the read-only loop
        synthesizing a structure summary when rounds run out."""
        instruction = Message(
            role="user",
            content=(
                "이제 도구를 사용하지 말고, 지금까지 조사한 내용을 바탕으로 사용자의 요청에 대한 "
                "구체적인 실행 계획만 작성하세요(코드 변경 없음). 형식:\n"
                "## 실행 계획\n1. 단계별 작업(무엇을·왜·어떻게)\n2. 영향 받는 파일/심볼\n"
                "3. 검증(테스트) 방법\n4. 위험과 대안\n"
                "마지막에 '실행하려면 /plan off 후 진행하세요.'를 덧붙이세요."
            ),
        )
        messages = condense_messages_for_model(
            [*runtime.messages, instruction],
            max_chars=window_aware_max_chars(
                context_window_tokens=getattr(turn_settings, "context_window_tokens", 0) or 0,
                max_output_tokens=getattr(turn_settings, "max_output_tokens", 8192) or 8192,
            ),
        )
        events, _timed = await self._stream_collector.collect(
            state=state,
            messages=messages,
            recovery=recovery,
            tool_schemas=[],
            stream_text=True,
            settings=turn_settings,
        )
        return (self._parser.parse_events(events).text or "").strip()

    async def _apply_steering(self, state: TurnState, runtime) -> None:
        """Drain mid-turn steering messages and inject them as user turns."""
        if self._steering is None:
            return
        for message in self._steering.drain():
            injected = Message(role="user", content=f"[사용자 추가 지시] {message}")
            runtime.messages.append(injected)
            state.messages.append(injected)
            await self._event_bus.publish(
                UserPromptSubmitted(
                    turn_id=state.turn_id,
                    message="Mid-turn steering message injected.",
                    data={"steering": message},
                )
            )

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
        # NOTE: auto-injecting file:line grounding for inspect turns (C) was tried
        # and MEASURED NEUTRAL — even handed the exact anchors, gpt-oss-120b reverted
        # to prose/package-role summaries instead of citing them, so it added rg +
        # context cost with no quality gain. The analysis-grounding gap vs codex is
        # model-bound (synthesis/instruction-following), not anchor-availability.
        completion_evidence.grounding_required = grounding_required(turn_input.user_prompt, routing)
        # Code-implementation turns stream from the implementation-tier model; all
        # other turns (planning, inspection, answers) use the base model.
        turn_settings = self._turn_settings(routing)

        for round_index in range(self._max_rounds):
            state.phase = "model"
            await self._apply_steering(state, runtime)
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
            exhausted = await apply_validation_control(self, state, control, runtime)
            if exhausted is not None:
                state.messages = runtime.messages
                return exhausted

            effective_inspect_round_budget = self._effective_inspect_round_budget(turn_input.user_prompt, routing, completion_evidence)
            effective_inspect_action_budget = self._effective_inspect_action_budget(turn_input.user_prompt, routing, completion_evidence)
            inspection_budget_available = self._inspection_budget_available(
                runtime.inspection_actions,
                runtime.inspection_rounds,
                action_budget=effective_inspect_action_budget,
                round_budget=effective_inspect_round_budget,
            )
            # Lock to mutation-only once the inspection budget is spent, or after
            # several mutation nudges. A small threshold (2) prematurely blocked
            # reads needed to understand a multi-file, cross-cutting change before
            # editing; the inspection budget remains the primary backstop.
            lock_to_mutation = runtime.mutation_action_pending and (
                not runtime.validation_repair_pending
                and (not inspection_budget_available or recovery.mutation_action_requests >= 4)
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
            runtime.messages, runtime.last_phase_prompt = self._phase_block.maybe_related_test_discovery_messages(
                runtime.messages,
                completion_evidence,
                phase_gate=phase_gate,
                last_phase_prompt=runtime.last_phase_prompt,
            )
            inspect_stage = await apply_inspect_stage(
                self,
                turn_input=turn_input,
                state=state,
                runtime=runtime,
                evidence=completion_evidence,
                routing=routing,
                round_index=round_index,
                inspect_round_budget=effective_inspect_round_budget,
            )
            injected = await maybe_inject_validation(
                self,
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

            if should_request_web_final_answer(
                routing,
                completion_evidence,
                runtime.messages,
                already_requested=runtime.external_final_answer_requested,
            ):
                if not runtime.external_final_answer_requested:
                    runtime.messages = self._prompt_builder.final_answer_request(
                        runtime.messages,
                        response_language=response_language(turn_input.user_prompt),
                    )
                runtime.external_final_answer_requested = True

            suppress_tools_for_final_answer = (
                runtime.inspect_final_answer_requested
                or runtime.external_final_answer_requested
                # Once a final answer has been requested after the change is done
                # (mutation- or validation-complete), suppress tools so the model
                # writes the narrative answer instead of calling another tool.
                or runtime.final_answer_after_change_requested
            )
            allowed_only = None
            if suppress_tools_for_final_answer:
                allowed_only = set()
            elif phase_gate.active:
                allowed_only = phase_gate.allowed_tool_names
            elif inspect_stage.active and not self._unified:
                # In the unified loop, inspection staging is ADVISORY: it still
                # tracks budget and nudges breadth, but it does not hard-restrict
                # the exposed tool schema. So the model can pick any tool it judges
                # necessary (e.g. write_file when a request was loosely worded and
                # routing only guessed "inspect"); read-only is still hard-enforced
                # by the policy when explicitly requested (read_only_requested / plan
                # mode), and mutations remain governed by the approval system.
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
            model_messages = runtime.messages
            if getattr(routing, "requires_mutation", False) or getattr(routing, "kind", "") == "modify":
                digest = build_task_loop_digest(
                    turn_input=turn_input,
                    routing=routing,
                    evidence=completion_evidence,
                    recovery_states=recovery.states,
                    current_step=phase_gate.phase,
                    next_required_action=phase_gate.required_next_action,
                )
                model_messages = task_loop_digest_messages(model_messages, digest)
            if suppress_tools_for_final_answer:
                final_language = response_language(turn_input.user_prompt)
                evidence_brief = ""
                if runtime.inspect_final_answer_requested:
                    evidence_brief = source_final_evidence_brief(
                        model_messages,
                        evidence=completion_evidence,
                        user_prompt=turn_input.user_prompt,
                        language=final_language,
                    )
                model_messages = final_answer_call_messages(
                    model_messages,
                    response_language=final_language,
                    evidence_brief=evidence_brief,
                )
            else:
                model_messages = condense_messages_for_model(
                    model_messages,
                    max_chars=window_aware_max_chars(
                        context_window_tokens=getattr(turn_settings, "context_window_tokens", 0) or 0,
                        max_output_tokens=getattr(turn_settings, "max_output_tokens", 8192) or 8192,
                    ),
                )
            # A (tool-call format at source): on a retry that follows a malformed
            # or pseudo (text-form) tool call, force a structured tool call so
            # gpt-oss emits a real tool_call instead of repeating floating text.
            # Strictly scoped to that recovery retry (the model already intended a
            # tool call), so good turns are never constrained. One-shot.
            call_settings = turn_settings
            if getattr(runtime, "force_structured_tool_call", False):
                runtime.force_structured_tool_call = False
                if tool_schemas and turn_settings is not None:
                    try:
                        forced_extra = dict(getattr(turn_settings, "extra_body", {}) or {})
                        forced_extra["tool_choice"] = "required"
                        call_settings = turn_settings.model_copy(update={"extra_body": forced_extra})
                    except Exception:
                        call_settings = turn_settings
            events, stream_timed_out = await self._stream_collector.collect(
                state=state,
                messages=model_messages,
                recovery=recovery,
                tool_schemas=tool_schemas,
                stream_text=not (routing.requires_external_knowledge and not has_tool_results),
                settings=call_settings,
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
                model=getattr(turn_settings, "model_name", None) or self._stream_collector.model_name,
            )
            if parsed.usage is not None:
                state.token_usage = parsed.usage

            if parsed.status == "ok_tool_calls":
                if runtime.external_final_answer_requested:
                    return LoopOutcome(
                        status="partial",
                        answer=web_evidence_fallback_answer(
                            prompt=turn_input.user_prompt,
                            messages=runtime.messages,
                            evidence=completion_evidence,
                            reason="model_requested_tool_after_web_finalization",
                            response_language=response_language(turn_input.user_prompt),
                        ),
                        error="Model requested another web tool after final-answer synthesis was required.",
                    )
                if runtime.final_answer_after_change_requested and mutation_complete(routing, completion_evidence):
                    return LoopOutcome(
                        status="success",
                        answer=evidence_answer(turn_input.user_prompt, completion_evidence, turn_input.workspace.root),
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
                    inspect_stage=inspect_stage,
                    more_mutation_before_validation=more_mutation,
                    round_index=round_index,
                )
            state.messages = runtime.messages
            if outcome is not None:
                return outcome

        state.messages = runtime.messages
        # Any non-mutation turn that gathered read/inspect evidence answers from
        # that evidence instead of dumping the raw "max_rounds_reached" block
        # message (e.g. a follow-up that tries to "run" a non-runnable artifact
        # like a markdown doc and exhausts rounds). Mutation turns keep their own
        # change-plan fallback below.
        # Plan mode: produce a model-written implementation plan instead of the
        # read-only structure-summary fallback.
        if getattr(turn_input, "plan_mode", False):
            plan = await self._plan_final_answer(state, runtime, recovery, turn_settings)
            if plan:
                return LoopOutcome(status="success", answer=plan)
        if not getattr(routing, "requires_mutation", False) and has_inspect_summary_evidence(completion_evidence):
            return LoopOutcome(
                status="partial",
                answer=grounded_inspect_summary(
                    messages=runtime.messages,
                    evidence=completion_evidence,
                    reason="max_rounds_reached",
                    response_language=response_language(turn_input.user_prompt),
                ),
                error="max_rounds_reached",
            )
        if should_request_web_final_answer(
            routing,
            completion_evidence,
            runtime.messages,
            already_requested=runtime.external_final_answer_requested,
        ):
            return LoopOutcome(
                status="partial",
                answer=web_evidence_fallback_answer(
                    prompt=turn_input.user_prompt,
                    messages=runtime.messages,
                    evidence=completion_evidence,
                    reason="max_rounds_reached",
                    response_language=response_language(turn_input.user_prompt),
                ),
                error="max_rounds_reached",
            )
        if (
            (getattr(routing, "requires_mutation", False) or getattr(routing, "kind", "") == "modify")
            and has_modify_plan_evidence(completion_evidence)
        ):
            return LoopOutcome(
                status="partial",
                answer=modify_change_plan_fallback(
                    prompt=turn_input.user_prompt,
                    evidence=completion_evidence,
                    language=response_language(turn_input.user_prompt),
                ),
                error="max_rounds_reached_without_file_change",
            )
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
        return update_repair_flags(turn_input, routing, evidence, runtime)

    @staticmethod
    def _snapshot(
        round_index: int,
        evidence: CompletionEvidence,
        recovery: RecoveryTracker,
        runtime: RoundRuntime,
    ):
        return round_state_snapshot(round_index, evidence, recovery, runtime)

    async def _record_recovery(self, state: TurnState, recovery: RecoveryTracker, reason, *, attempts: int = 0, last_error: str | None = None, blocked: bool = False) -> None:
        recovery.add_state(reason, attempts=attempts, last_error=last_error, blocked=blocked)
        latest = recovery.states[-1]
        await self._publish(RecoveryStateUpdated(turn_id=state.turn_id, message=f"Recovery state updated: {latest.reason}.", data=latest.model_dump(mode="json")))
    async def _publish(self, event) -> None:
        await self._event_bus.publish(event)
    def _inspection_budget_available(
        self,
        inspection_actions: int,
        inspection_rounds: int,
        *,
        action_budget: int | None = None,
        round_budget: int | None = None,
    ) -> bool:
        return inspection_budget_available(
            inspection_actions,
            inspection_rounds,
            default_action_budget=self._inspect_action_budget,
            default_round_budget=self._inspect_round_budget,
            action_budget=action_budget,
            round_budget=round_budget,
        )
    def _effective_inspect_action_budget(self, prompt: str, routing, evidence: CompletionEvidence) -> int:
        return effective_inspect_action_budget(
            prompt,
            routing,
            evidence,
            default_budget=self._inspect_action_budget,
        )
    def _effective_inspect_round_budget(self, prompt: str, routing, evidence: CompletionEvidence) -> int:
        return effective_inspect_round_budget(
            prompt,
            routing,
            evidence,
            default_budget=self._inspect_round_budget,
            max_rounds=self._max_rounds,
        )
    def _can_retry_phase_block(self, counts: dict[tuple[str, str], int], *, phase_gate, reason: str, max_attempts: int = 2) -> bool:
        return PhaseBlockHelper.can_retry(counts, phase_gate=phase_gate, reason=reason, max_attempts=max_attempts)
    def _should_inject_validation_action(self, round_index: int, routing, evidence: CompletionEvidence, recovery: RecoveryTracker, *, validation_action_pending: bool, awaiting_revalidation_after_mutation: bool) -> bool:
        return self._revalidation.should_inject(round_index, routing, evidence, recovery, validation_action_pending=validation_action_pending, awaiting_revalidation_after_mutation=awaiting_revalidation_after_mutation)
    async def _execute_validation_fallback(self, turn_input: TurnInput, state: TurnState, loop_guard: ToolLoopGuard, recovery: RecoveryTracker, completion_evidence: CompletionEvidence, routing, *, phase_gate) -> list[ToolResult]:
        return await self._revalidation.execute(turn_input, state, loop_guard, recovery, completion_evidence, routing, phase_gate=phase_gate)

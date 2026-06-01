"""Minimal provider-neutral ReAct loop for fake LLM integration."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from allCode.agent.completion_gate import tool_loop_signatures
from allCode.agent.context import ContextBuilder
from allCode.agent.policy import ToolPolicy
from allCode.agent.prompt_builder import PromptBuilder
from allCode.agent.recovery import RecoveryTracker, ToolLoopGuard, needs_validation_repair
from allCode.agent.router import RuleBasedRouter
from allCode.agent.tool_targets import ToolTargetRecorder
from allCode.agent.turn_completion import LoopOutcome, finalize_completion
from allCode.agent.workflow import GenerationWorkflow
from allCode.agent.workflow_routing import should_use_generation_workflow
from allCode.core.event_bus import AsyncEventBus, EventBus
from allCode.core.events import (
    FinalAnswerReady,
    ModelStreamHeartbeat,
    ModelStreamStarted,
    ModelStreamTimedOut,
    ModelTextDelta,
    ToolCallRequested,
    ToolExecutionFinished,
    ToolExecutionStarted,
    ToolLoopDetected,
    TurnFailed,
    TurnStarted,
)
from allCode.core.models import Message, ToolResult, TurnInput, TurnState
from allCode.core.result import CompletionEvidence, TurnResult
from allCode.llm.client import LLMClient
from allCode.llm.response_parser import ResponseParser
from allCode.llm.settings import ModelSettings, ToolSchema
from allCode.tools.base import ToolContext
from allCode.tools.approval import ApprovalManager
from allCode.tools.executor import ToolExecutor
from allCode.tools.registry import ToolRegistry

class AgentLoop:
    def __init__(
        self,
        *,
        llm_client: LLMClient,
        settings: ModelSettings,
        tools: ToolRegistry | None = None,
        event_bus: EventBus | None = None,
        max_rounds: int = 12,
        prompt_builder: PromptBuilder | None = None,
        heartbeat_interval_seconds: float = 5.0,
        stream_timeout_seconds: float = 60.0,
        router: RuleBasedRouter | None = None,
        tool_policy: ToolPolicy | None = None,
        approval: ApprovalManager | None = None,
        tool_executor: ToolExecutor | None = None,
        generation_workflow: GenerationWorkflow | None = None,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._settings = settings
        self._tools = tools or ToolRegistry()
        self._event_bus = event_bus or AsyncEventBus()
        self._max_rounds = max_rounds
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._parser = ResponseParser()
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._stream_timeout_seconds = stream_timeout_seconds
        self._router = router or RuleBasedRouter()
        self._tool_policy = tool_policy or ToolPolicy()
        self._approval = approval or ApprovalManager()
        self._tool_executor = tool_executor or ToolExecutor(
            registry=self._tools,
            policy=self._tool_policy,
            approval=self._approval,
        )
        self._generation_workflow = generation_workflow or GenerationWorkflow(event_bus=self._event_bus)
        self._context_builder = context_builder
        self._target_recorder = ToolTargetRecorder(context_builder)

    async def run_turn(self, turn_input: TurnInput) -> TurnResult:
        routing = self._router.classify(turn_input.user_prompt)
        if should_use_generation_workflow(turn_input.user_prompt, routing):
            workflow_result = await self._generation_workflow.run(turn_input)
            return workflow_result.turn_result
        context_bundle = None
        if self._context_builder is not None:
            context_bundle = await self._context_builder.build(turn_input)
        state = TurnState(messages=self._prompt_builder.initial_messages(turn_input, routing, context_bundle))
        recovery = RecoveryTracker()
        loop_guard = ToolLoopGuard()
        completion_evidence = CompletionEvidence()
        await self._publish(TurnStarted(turn_id=state.turn_id, message="Turn started."))

        try:
            outcome = await self._run_rounds(turn_input, state, recovery, loop_guard, completion_evidence, routing)
            finalized = finalize_completion(
                turn_input=turn_input,
                state=state,
                routing=routing,
                outcome_status=outcome.status,
                outcome_answer=outcome.answer,
                outcome_error=outcome.error,
                base_evidence=completion_evidence,
            )
            if finalized.status == "success" and finalized.evidence.final_answer_ready:
                state.phase = "final"
                await self._publish(
                    FinalAnswerReady(
                        turn_id=state.turn_id,
                        message="Final answer ready.",
                        final_answer=outcome.answer,
                    )
                )
            return TurnResult(
                turn_id=state.turn_id,
                status=finalized.status,
                final_answer=outcome.answer if finalized.evidence.final_answer_ready or finalized.status == "partial" else "",
                created_files=state.created_files,
                modified_files=state.modified_files,
                token_usage=state.token_usage,
                error_message=finalized.error_message,
                completion_evidence=finalized.evidence,
                recovery_states=recovery.states,
                tool_loop_signatures=tool_loop_signatures(loop_guard),
                requires_change_evidence=finalized.requires_change,
                validation_required=routing.requires_validation,
            )
        except asyncio.CancelledError:
            state.phase = "failed"
            await self._publish(
                TurnFailed(
                    turn_id=state.turn_id,
                    message="Turn cancelled.",
                    error_type="cancelled",
                    cancelled=True,
                )
            )
            return TurnResult(
                turn_id=state.turn_id,
                status="cancelled",
                error_message="cancelled",
                recovery_states=recovery.states,
            )
        except Exception as exc:
            state.phase = "failed"
            await self._publish(
                TurnFailed(
                    turn_id=state.turn_id,
                    message=str(exc),
                    error_type=exc.__class__.__name__,
                )
            )
            return TurnResult(
                turn_id=state.turn_id,
                status="failed",
                error_message=str(exc),
                recovery_states=recovery.states,
            )

    async def _run_rounds(
        self,
        turn_input: TurnInput,
        state: TurnState,
        recovery: RecoveryTracker,
        loop_guard: ToolLoopGuard,
        completion_evidence: CompletionEvidence,
        routing,
    ) -> LoopOutcome:
        messages = list(state.messages)
        for round_index in range(self._max_rounds):
            state.phase = "model"
            await self._publish(
                ModelStreamStarted(
                    turn_id=state.turn_id,
                    message=f"Model stream started for round {round_index + 1}.",
                    data={"round": round_index + 1, "retry": round_index > 0},
                )
            )
            has_tool_results = any(message.role == "tool" for message in messages)
            stream_text = not (routing.requires_external_knowledge and not has_tool_results)
            events, stream_timed_out = await self._collect_model_events(
                state=state,
                messages=messages,
                recovery=recovery,
                stream_text=stream_text,
            )
            if stream_timed_out and not events and recovery.can_retry_stream_timeout():
                state.phase = "recovery"
                messages = self._prompt_builder.empty_response_retry(messages)
                continue
            if stream_timed_out and not events:
                return LoopOutcome(status="failed", error="Model stream timed out without usable output.")
            parsed = self._parser.parse_events(events)
            if parsed.usage is not None:
                state.token_usage = parsed.usage

            if parsed.status == "empty_response" and recovery.can_retry_empty_response():
                state.phase = "recovery"
                recovery.add_state("empty_response", attempts=1)
                messages = self._prompt_builder.empty_response_retry(messages)
                continue
            if parsed.status == "empty_response":
                recovery.add_state("empty_response", attempts=2, blocked=True)
                return LoopOutcome(status="failed", error="Model returned an empty response after retry.")

            if parsed.status == "reasoning_only" and needs_validation_repair(routing, completion_evidence):
                if recovery.can_request_validation_repair():
                    state.phase = "recovery"
                    recovery.add_state(
                        "validation_failed",
                        attempts=recovery.validation_repair_requests,
                        last_error="model produced reasoning-only content after failed validation",
                    )
                    messages = self._prompt_builder.validation_repair_request(messages)
                    continue
            if parsed.status == "reasoning_only" and recovery.can_request_final_answer():
                state.phase = "recovery"
                recovery.add_state("reasoning_only", attempts=1)
                messages = self._prompt_builder.final_answer_request(messages)
                continue
            if parsed.status == "reasoning_only":
                recovery.add_state("reasoning_only", attempts=2, blocked=True)
                return LoopOutcome(status="failed", error="Model returned reasoning-only content after retry.")

            if parsed.status == "ok_tool_calls":
                state.phase = "tools"
                results = await self._execute_tool_calls(
                    turn_input,
                    state,
                    parsed.tool_calls,
                    loop_guard,
                    recovery,
                    completion_evidence,
                    routing,
                )
                messages.append(Message(role="assistant", content=parsed.text, tool_calls=parsed.tool_calls))
                messages = self._prompt_builder.append_tool_results(messages, results)
                if any(result.is_final and result.ok for result in results):
                    return LoopOutcome(
                        status="success",
                        answer=next(result.content for result in results if result.is_final and result.ok),
                    )
                continue

            if parsed.status == "length_cutoff":
                recovery.add_state("length_cutoff", attempts=1, last_error="model response hit length limit")
                return LoopOutcome(status="partial", answer=parsed.text.rstrip())

            if parsed.status == "malformed_tool_call":
                return LoopOutcome(
                    status="failed",
                    error=f"Model response could not be parsed safely: {parsed.error or 'malformed tool call'}",
                )

            if parsed.text.strip():
                if needs_validation_repair(routing, completion_evidence) and recovery.can_request_validation_repair():
                    state.phase = "recovery"
                    recovery.add_state(
                        "validation_failed",
                        attempts=recovery.validation_repair_requests,
                        last_error="model answered before validation passed",
                    )
                    messages.append(Message(role="assistant", content=parsed.text.rstrip()))
                    messages = self._prompt_builder.validation_repair_request(messages)
                    continue
                return LoopOutcome(status="success", answer=parsed.text.rstrip())

        return LoopOutcome(
            status="partial",
            answer="",
            error="The turn reached the maximum number of model rounds before a final answer was produced.",
        )

    async def _collect_model_events(
        self,
        *,
        state: TurnState,
        messages: Sequence[Message],
        recovery: RecoveryTracker,
        stream_text: bool = True,
    ) -> tuple[list, bool]:
        iterator = self._llm_client.stream(messages, self._tool_schemas(), self._settings).__aiter__()
        events = []
        heartbeat_count = 0
        started_at = asyncio.get_running_loop().time()
        next_event_task = asyncio.create_task(anext(iterator))
        while True:
            elapsed = asyncio.get_running_loop().time() - started_at
            remaining_timeout = max(0.0, self._stream_timeout_seconds - elapsed)
            if remaining_timeout <= 0:
                recovery.add_state("stream_timeout", attempts=heartbeat_count, blocked=not bool(events))
                await self._publish(
                    ModelStreamTimedOut(
                        turn_id=state.turn_id,
                        message="Model stream timed out.",
                    )
                )
                next_event_task.cancel()
                return events, True
            wait_seconds = min(self._heartbeat_interval_seconds, remaining_timeout)
            done, _pending = await asyncio.wait({next_event_task}, timeout=wait_seconds)
            if not done:
                heartbeat_count += 1
                recovery.add_state("slow_stream", attempts=heartbeat_count)
                await self._publish(
                    ModelStreamHeartbeat(
                        turn_id=state.turn_id,
                        message="Model stream heartbeat.",
                        data={"heartbeat_count": heartbeat_count},
                    )
                )
                continue
            try:
                event = next_event_task.result()
            except StopAsyncIteration:
                return events, False
            events.append(event)
            next_event_task = asyncio.create_task(anext(iterator))
            if stream_text and event.kind == "text_delta" and event.text:
                await self._publish(
                    ModelTextDelta(
                        turn_id=state.turn_id,
                        message=event.text,
                        delta=event.text,
                    )
                )

    async def _execute_tool_calls(
        self,
        turn_input: TurnInput,
        state: TurnState,
        tool_calls: Sequence,
        loop_guard: ToolLoopGuard,
        recovery: RecoveryTracker,
        completion_evidence: CompletionEvidence,
        routing,
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        context = ToolContext(
            workspace=turn_input.workspace,
            session_id=turn_input.session_id,
            turn_id=state.turn_id,
            approval_mode=self._approval.mode,
        )
        for tool_call in tool_calls:
            state.tool_calls.append(tool_call)
            await self._publish(
                ToolCallRequested(
                    turn_id=state.turn_id,
                    message=f"Tool requested: {tool_call.name}",
                    tool_call=tool_call,
                )
            )
            signature, loop_detected = loop_guard.record(tool_call)
            if loop_detected:
                recovery.add_state("tool_loop", attempts=signature.count, blocked=True)
                await self._publish(
                    ToolLoopDetected(
                        turn_id=state.turn_id,
                        message="Repeated identical tool call detected.",
                        tool_call=tool_call,
                        data={"signature": signature.model_dump(mode="json")},
                    )
                )
                results.append(
                    ToolResult(
                        call_id=tool_call.id,
                        name=tool_call.name,
                        ok=False,
                        error="Repeated identical tool call blocked by loop guard.",
                        error_type="tool_loop_detected",
                    )
                )
                continue

            result = await self._tool_executor.execute(
                tool_call,
                context,
                routing=routing,
                completion_evidence=completion_evidence,
                event_bus=self._event_bus,
            )
            self._target_recorder.record(state, result)
            results.append(result)
        return results

    def _tool_schemas(self) -> list[ToolSchema]:
        return [
            ToolSchema(
                name=definition.name,
                description=definition.description,
                parameters=definition.parameters,
            )
            for definition in self._tools.definitions()
        ]

    async def _publish(self, event) -> None:
        await self._event_bus.publish(event)

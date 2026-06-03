"""Minimal provider-neutral ReAct loop for fake LLM integration."""

from __future__ import annotations

import asyncio
from pathlib import Path

from allCode.agent.completion_gate import tool_loop_signatures
from allCode.agent.context import ContextBuilder
from allCode.agent.finalization_helpers import (
    final_answer_for_result,
)
from allCode.agent.finalization import apply_final_answer_policy
from allCode.agent.policy import ToolPolicy
from allCode.agent.preflight import (
    PreflightPlanner,
    followup_target_hint,
    missing_read_search_fallback,
    should_force_mutation_after_inspection,
)
from allCode.agent.prompt_builder import PromptBuilder
from allCode.agent.phase_gate import seed_known_artifact_targets
from allCode.agent.model_router import ModelRouter
from allCode.agent.recovery import RecoveryTracker, ToolLoopGuard
from allCode.agent.router import RuleBasedRouter
from allCode.agent.round_runner import RoundRunner
from allCode.agent.stream_collector import ModelStreamCollector
from allCode.agent.tool_call_processor import ToolCallProcessor
from allCode.agent.tool_targets import ToolTargetRecorder
from allCode.agent.turn_completion import LoopOutcome, finalize_completion
from allCode.agent.workflow import GenerationWorkflow
from allCode.agent.workflow_routing import should_use_generation_workflow
from allCode.core.event_bus import AsyncEventBus, EventBus
from allCode.core.events import (
    ContextBuilt,
    FinalAnswerReady,
    RoutingDecided,
    TurnFailed,
    TurnResultReady,
    TurnStarted,
)
from allCode.core.models import Message, TurnInput, TurnState
from allCode.core.result import CompletionEvidence, TurnResult
from allCode.llm.client import LLMClient
from allCode.llm.settings import ModelSettings
from allCode.memory.project_obligations import feature_objectives_from_prompt
from allCode.tools.approval import ApprovalManager
from allCode.tools.builtin import builtin_tools
from allCode.tools.executor import ToolExecutor
from allCode.tools.registry import ToolRegistry
from allCode.workspace.git_state import append_git_summary


class AgentLoop:
    """The central coordinator for agent turns, routing, preflight, and round runner delegation."""

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
        model_router: ModelRouter | None = None,
        tool_policy: ToolPolicy | None = None,
        approval: ApprovalManager | None = None,
        tool_executor: ToolExecutor | None = None,
        generation_workflow: GenerationWorkflow | None = None,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._settings = settings
        self._tools = tools or ToolRegistry(builtin_tools())
        self._event_bus = event_bus or AsyncEventBus()
        self._max_rounds = max_rounds
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._stream_timeout_seconds = stream_timeout_seconds
        self._router = router or RuleBasedRouter()
        self._model_router = model_router
        self._tool_policy = tool_policy or ToolPolicy()
        self._approval = approval or ApprovalManager()
        self._tool_executor = tool_executor or ToolExecutor(
            registry=self._tools,
            policy=self._tool_policy,
            approval=self._approval,
        )
        self._generation_workflow = generation_workflow or GenerationWorkflow(
            event_bus=self._event_bus,
            tool_executor=self._tool_executor,
            router=self._router,
            llm_client=self._llm_client,
            settings=self._settings,
        )
        self._context_builder = context_builder
        session_state = context_builder.session_state if context_builder is not None else None
        self._target_recorder = ToolTargetRecorder(context_builder)
        self._preflight = PreflightPlanner()
        self._tool_call_processor = ToolCallProcessor(
            tools=self._tools,
            event_bus=self._event_bus,
            tool_policy=self._tool_policy,
            approval=self._approval,
            tool_executor=self._tool_executor,
            target_recorder=self._target_recorder,
            observation_cache=session_state.observation_cache if session_state is not None else None,
            tool_budget=session_state.tool_budget if session_state is not None else None,
            action_ledger=session_state.action_ledger if session_state is not None else None,
        )
        self._stream_collector = ModelStreamCollector(
            llm_client=self._llm_client,
            settings=self._settings,
            event_bus=self._event_bus,
            heartbeat_interval_seconds=self._heartbeat_interval_seconds,
            stream_timeout_seconds=self._stream_timeout_seconds,
        )
        self._round_runner = RoundRunner(
            llm_client=self._llm_client,
            settings=self._settings,
            event_bus=self._event_bus,
            prompt_builder=self._prompt_builder,
            tool_call_processor=self._tool_call_processor,
            stream_collector=self._stream_collector,
            max_rounds=self._max_rounds,
        )

    async def run_turn(self, turn_input: TurnInput) -> TurnResult:
        state = TurnState()
        await self._publish(
            TurnStarted(
                turn_id=state.turn_id,
                message="Turn started.",
                data={"session_id": turn_input.session_id},
            )
        )
        context_bundle = None
        if self._context_builder is not None:
            state.phase = "context"
            context_bundle = await self._context_builder.build(turn_input)
        if context_bundle is not None:
            await self._publish(
                ContextBuilt(
                    turn_id=state.turn_id,
                    message="Context built.",
                    data={
                        "section_count": len(context_bundle.sections),
                        "sections": [
                            {
                                "name": section.name,
                                "source": section.source,
                                "section_type": section.section_type,
                                "token_estimate": section.token_estimate,
                            }
                            for section in context_bundle.sections
                        ],
                    },
                )
            )
        state.phase = "routing"
        recent_targets = []
        if self._context_builder is not None:
            recent_targets = [
                *self._context_builder.manifest_recent_paths(),
                *self._context_builder.recent_targets.recent_paths(),
            ]
        if self._model_router is not None:
            routing = await self._model_router.classify(
                turn_input.user_prompt,
                context_bundle=context_bundle,
                recent_targets=recent_targets,
            )
        else:
            routing = self._router.classify(turn_input.user_prompt)
        if routing.kind in {"inspect", "modify", "operate"}:
            manifest_target = (
                self._context_builder.followup_manifest_target(
                    turn_input.user_prompt,
                    workspace_root=turn_input.workspace.root,
                )
                if self._context_builder is not None
                else None
            )
            target_hint = manifest_target or followup_target_hint(turn_input.user_prompt, recent_targets)
            if target_hint is not None and (
                routing.target_hint is None
                or not self._target_hint_exists(turn_input.workspace.root, routing.target_hint)
            ):
                routing = routing.model_copy(update={"target_hint": target_hint})
        await self._publish(
            RoutingDecided(
                turn_id=state.turn_id,
                message=f"Routing decided: {routing.kind}.",
                data=routing.model_dump(mode="json"),
            )
        )
        if should_use_generation_workflow(turn_input.user_prompt, routing, workspace_root=turn_input.workspace.root):
            workflow_result = await self._generation_workflow.run(turn_input, routing=routing)
            if self._context_builder is not None:
                for path in [*workflow_result.turn_result.created_files, *workflow_result.turn_result.modified_files]:
                    self._context_builder.remember_target(path, turn_id=workflow_result.turn_result.turn_id, summary="generation workflow output")
                self._context_builder.session_state.remember_turn_outcome(
                    workflow_result.turn_result.completion_evidence,
                    status=workflow_result.turn_result.status,
                    workspace_root=turn_input.workspace.root,
                )
            return workflow_result.turn_result
        state.messages = self._prompt_builder.initial_messages(turn_input, routing, context_bundle)
        recovery = RecoveryTracker()
        loop_guard = ToolLoopGuard()
        completion_evidence = CompletionEvidence()
        self._seed_session_artifact_obligations(turn_input, completion_evidence)
        force_mutation_action = False

        try:
            preflight = self._preflight.plan(prompt=turn_input.user_prompt, routing=routing)
            if preflight.clarification_answer is not None:
                outcome = LoopOutcome(
                    status="partial",
                    answer=preflight.clarification_answer,
                    error="target_clarification_required",
                )
            else:
                if preflight.tool_calls:
                    state.phase = "tools"
                    preflight_results = await self._tool_call_processor.execute(
                        turn_input,
                        state,
                        preflight.tool_calls,
                        loop_guard,
                        recovery,
                        completion_evidence,
                        routing,
                    )
                    state.messages.append(Message(role="assistant", content="", tool_calls=preflight.tool_calls))
                    state.messages = self._prompt_builder.append_tool_results(state.messages, preflight_results)
                    fallback_calls = missing_read_search_fallback(preflight.tool_calls, preflight_results, routing)
                    if fallback_calls:
                        fallback_results = await self._tool_call_processor.execute(
                            turn_input,
                            state,
                            fallback_calls,
                            loop_guard,
                            recovery,
                            completion_evidence,
                            routing,
                        )
                        state.messages.append(Message(role="assistant", content="", tool_calls=fallback_calls))
                        state.messages = self._prompt_builder.append_tool_results(state.messages, fallback_results)
                    force_mutation_action = should_force_mutation_after_inspection(
                        preflight_results,
                        routing,
                        completion_evidence,
                    )
                    if force_mutation_action:
                        state.messages = self._prompt_builder.mutation_action_request(state.messages)
                outcome = await self._round_runner.run_rounds(
                    turn_input,
                    state,
                    recovery,
                    loop_guard,
                    completion_evidence,
                    routing,
                    force_mutation_action=force_mutation_action,
                )
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
            final_answer = final_answer_for_result(
                self._prompt_builder,
                finalized_status=finalized.status,
                evidence_ready=finalized.evidence.final_answer_ready,
                outcome_answer=outcome.answer,
                error_message=finalized.error_message or outcome.error,
                messages=state.messages,
            )
            final_answer = apply_final_answer_policy(
                final_answer,
                routing=routing,
                prompt=turn_input.user_prompt,
                evidence=finalized.evidence,
                messages=state.messages,
            )
            final_answer = append_git_summary(
                final_answer,
                workspace_root=turn_input.workspace.root,
                evidence=finalized.evidence,
            )
            result = TurnResult(
                turn_id=state.turn_id,
                status=finalized.status,
                final_answer=final_answer,
                created_files=state.created_files,
                modified_files=state.modified_files,
                deleted_files=state.deleted_files,
                validation_passed=finalized.evidence.validation_passed,
                token_usage=state.token_usage,
                error_message=finalized.error_message,
                completion_evidence=finalized.evidence,
                recovery_states=recovery.states,
                tool_loop_signatures=tool_loop_signatures(loop_guard),
                requires_change_evidence=finalized.requires_change,
                validation_required=routing.requires_validation and routing.requires_mutation,
            )
            if self._context_builder is not None:
                self._context_builder.session_state.remember_turn_outcome(
                    result.completion_evidence,
                    status=result.status,
                    workspace_root=turn_input.workspace.root,
                )
            await self._publish(
                TurnResultReady(
                    turn_id=state.turn_id,
                    message=f"Turn result ready: {result.status}.",
                    data=result.model_dump(mode="json"),
                )
            )
            return result
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
            result = TurnResult(
                turn_id=state.turn_id,
                status="cancelled",
                error_message="cancelled",
                recovery_states=recovery.states,
            )
            await self._publish(
                TurnResultReady(
                    turn_id=state.turn_id,
                    message="Turn result ready: cancelled.",
                    data=result.model_dump(mode="json"),
                )
            )
            return result
        except Exception as exc:
            state.phase = "failed"
            await self._publish(
                TurnFailed(
                    turn_id=state.turn_id,
                    message=str(exc),
                    error_type=exc.__class__.__name__,
                )
            )
            result = TurnResult(
                turn_id=state.turn_id,
                status="failed",
                error_message=str(exc),
                recovery_states=recovery.states,
            )
            await self._publish(
                TurnResultReady(
                    turn_id=state.turn_id,
                    message="Turn result ready: failed.",
                    data=result.model_dump(mode="json"),
                )
            )
            return result

    async def _publish(self, event) -> None:
        await self._event_bus.publish(event)

    def _seed_session_artifact_obligations(self, turn_input: TurnInput, evidence: CompletionEvidence) -> None:
        for objective in feature_objectives_from_prompt(turn_input.user_prompt):
            if objective not in evidence.feature_objectives:
                evidence.feature_objectives.append(objective)
        if self._context_builder is None:
            return
        obligations = self._context_builder.session_state.active_project_obligations
        if obligations is None:
            return
        for objective in obligations.feature_objectives:
            if objective not in evidence.feature_objectives:
                evidence.feature_objectives.append(objective)
        seed_known_artifact_targets(
            turn_input.user_prompt,
            evidence,
            workspace_root=turn_input.workspace.root,
            source_files=obligations.source_files,
            test_files=obligations.test_files,
        )

    @staticmethod
    def _target_hint_exists(workspace_root: str, target_hint: str) -> bool:
        candidate = Path(target_hint)
        if not candidate.is_absolute():
            candidate = Path(workspace_root) / candidate
        try:
            return candidate.expanduser().resolve().exists()
        except OSError:
            return False

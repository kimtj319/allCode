"""Minimal provider-neutral ReAct loop for fake LLM integration."""

from __future__ import annotations

import asyncio

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
from allCode.agent.model_router import ModelRouter
from allCode.agent.loop_obligations import remember_generation_workflow_result, seed_session_artifact_obligations, target_hint_exists
from allCode.agent.recovery import RecoveryTracker, ToolLoopGuard
from allCode.agent.router import RuleBasedRouter, _references_prior_conversation
from allCode.agent.round_runner import RoundRunner
from allCode.agent.stream_collector import ModelStreamCollector
from allCode.agent.tool_call_processor import ToolCallProcessor
from allCode.agent.tool_targets import ToolTargetRecorder
from allCode.agent.turn_completion import LoopOutcome, finalize_completion
from allCode.agent.modify_fallback import has_modify_plan_evidence, modify_change_plan_fallback
from allCode.agent.round_runner_helpers import response_language
from allCode.agent.workflow import GenerationWorkflow
from allCode.agent.workflow_routing import should_use_generation_workflow
from allCode.core.event_bus import AsyncEventBus, EventBus
from allCode.core.events import (
    ContextBuilt,
    FinalAnswerReady,
    RoutingDecided,
    TurnFailed,
    TurnFinalized,
    TurnResultReady,
    TurnStarted,
)
from allCode.core.models import Message, ToolCall, TurnInput, TurnState
from allCode.tools.base import ToolContext
from allCode.core.result import CompletionEvidence, TurnResult
from allCode.llm.client import LLMClient
from allCode.llm.settings import ModelSettings
from allCode.tools.approval import ApprovalHandler, ApprovalManager
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
        implementation_settings: ModelSettings | None = None,
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
        approval_handler: ApprovalHandler | None = None,
        tool_executor: ToolExecutor | None = None,
        generation_workflow: GenerationWorkflow | None = None,
        context_builder: ContextBuilder | None = None,
        hook_runner=None,
    ) -> None:
        self._llm_client = llm_client
        self._settings = settings
        self._implementation_settings = implementation_settings or settings
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
            approval_handler=approval_handler,
            hook_runner=hook_runner,
        )
        self._generation_workflow = generation_workflow or GenerationWorkflow(
            event_bus=self._event_bus,
            tool_executor=self._tool_executor,
            router=self._router,
            llm_client=self._llm_client,
            settings=self._settings,
            editor_settings=self._implementation_settings,
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
        # Questions that refer back to the conversation must be answered from chat
        # context, so bypass the LLM router (which classifies them as source
        # inspection) and use the rule router's conversation-recall handling.
        if self._model_router is not None and not _references_prior_conversation(turn_input.user_prompt):
            routing = await self._model_router.classify(
                turn_input.user_prompt,
                context_bundle=context_bundle,
                recent_targets=recent_targets,
            )
            # Guardrails against LLM-router misroutes, using the deterministic rule
            # router as a cross-check:
            #  - a clear change/run request ("...추가해줘", "...수정해줘") wrongly
            #    downgraded to a chat answer (so it describes edits instead of
            #    applying them);
            #  - a web/external-knowledge question ("spring cloud ... 검색해서
            #    정리해줘") wrongly sent into local source inspection (so it probes
            #    the repo and contaminates the answer with package analysis).
            if routing.kind in {"answer", "inspect"}:
                rule_routing = self._router.classify(turn_input.user_prompt)
                if routing.kind == "answer" and rule_routing.kind in {"modify", "operate"}:
                    routing = rule_routing
                elif (
                    routing.kind == "inspect"
                    and rule_routing.kind == "answer"
                    and rule_routing.requires_external_knowledge
                    and not routing.target_hint
                ):
                    routing = rule_routing
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
                or not target_hint_exists(turn_input.workspace.root, routing.target_hint)
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
            remember_generation_workflow_result(
                self._context_builder,
                workflow_result,
                workspace_root=turn_input.workspace.root,
            )
            return workflow_result.turn_result
        state.messages = self._prompt_builder.initial_messages(turn_input, routing, context_bundle)
        recovery = RecoveryTracker()
        loop_guard = ToolLoopGuard()
        completion_evidence = CompletionEvidence()
        seed_session_artifact_obligations(turn_input, completion_evidence, routing, self._context_builder)
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
            # Auto-validate after edit: a modify turn may apply a correct change but
            # never call run_tests itself, leaving validation unmet. Run the detected
            # validation command once so a legitimate edit completes instead of
            # failing on missing validation.
            if (
                outcome.status != "success"
                and (getattr(routing, "requires_mutation", False) or getattr(routing, "kind", "") == "modify")
                and not getattr(routing, "read_only_requested", False)
                and completion_evidence.has_file_change()
                and completion_evidence.validation_passed is not True
            ):
                await self._auto_validate_after_edit(turn_input, state, routing, completion_evidence)
                if completion_evidence.validation_passed is True:
                    outcome = LoopOutcome(
                        status="success",
                        answer=outcome.answer if outcome.answer.strip() else "요청한 변경을 적용하고 검증했습니다.",
                        error=None,
                    )
            # Graceful degradation: a modify turn that inspected the code but never
            # produced a file change would otherwise return a bare block-reason
            # failure. Replace it with a grounded change plan (clearly not applied)
            # regardless of which exit path the loop took.
            if (
                outcome.status != "success"
                and (getattr(routing, "requires_mutation", False) or getattr(routing, "kind", "") == "modify")
                and has_modify_plan_evidence(completion_evidence)
            ):
                outcome = LoopOutcome(
                    status=outcome.status,
                    answer=modify_change_plan_fallback(
                        prompt=turn_input.user_prompt,
                        evidence=completion_evidence,
                        language=response_language(turn_input.user_prompt),
                    ),
                    error=outcome.error or "max_rounds_reached_without_file_change",
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
            final_answer_published = False
            if finalized.status == "success" and finalized.evidence.final_answer_ready:
                state.phase = "final"
                await self._publish(
                    FinalAnswerReady(
                        turn_id=state.turn_id,
                        message="Final answer ready.",
                        final_answer=outcome.answer,
                    )
                )
                final_answer_published = True
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
            if not final_answer_published and result.final_answer.strip():
                await self._publish(
                    TurnFinalized(
                        turn_id=state.turn_id,
                        message=f"Turn finalized: {result.status}.",
                        status=result.status,
                        final_answer=result.final_answer,
                    )
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

    async def _auto_validate_after_edit(
        self,
        turn_input: TurnInput,
        state: TurnState,
        routing,
        completion_evidence: CompletionEvidence,
    ) -> None:
        """Run the detected validation command once when a modify turn applied a
        file change but never validated. run_tests infers the command and project
        root, and treats a project with no test suite as satisfied-by-absence."""

        call = ToolCall(
            id=f"autovalidate-{state.turn_id}",
            name="run_tests",
            arguments={"command": "", "cwd": "."},
        )
        context = ToolContext(
            workspace=turn_input.workspace,
            session_id=turn_input.session_id or state.turn_id,
            turn_id=state.turn_id,
            approval_mode="auto",
        )
        try:
            await self._tool_executor.execute(
                call,
                context,
                routing=routing,
                completion_evidence=completion_evidence,
                event_bus=self._event_bus,
            )
        except Exception:
            # Auto-validation is best-effort; never let it crash the turn.
            return

    async def _publish(self, event) -> None:
        await self._event_bus.publish(event)

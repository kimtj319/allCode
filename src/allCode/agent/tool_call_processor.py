"""Tool-call policy, loop guarding, execution, and schema filtering."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.agent.policy import ToolPolicy, policy_denied_tool_result
from allCode.agent.phase_gate import PhaseToolGate
from allCode.agent.recovery import RecoveryTracker, ToolLoopGuard
from allCode.agent.read_only_guard import read_only_tool_denial
from allCode.agent.inspect_tool_normalization import normalize_inspect_stage_call
from allCode.agent.tool_action_ledger import ToolActionLedger
from allCode.agent.tool_evidence import ToolEvidenceRecorder
from allCode.agent.tool_schema_denial import deny_tool_schema
from allCode.agent.tool_schema_filter import ToolSchemaFilter, normalize_tool_call_for_routing
from allCode.agent.tool_schema_validation import strip_harmless_extra_arguments, validate_tool_arguments
from allCode.agent.tool_phase_target import phase_target_denial
from allCode.agent.tool_targets import ToolTargetRecorder
from allCode.core.event_bus import EventBus
from allCode.agent.tool_orchestrator import (
    ObservationCache,
    PatchFailureTracker,
    ToolBudgetTracker,
    suppressed_tool_result,
)
from allCode.agent.validation_repair import attach_validation_failure_summary
from allCode.core.events import (
    RecoveryStateUpdated,
    ToolCallRequested,
    ToolCallSuppressed,
    ToolLoopDetected,
    ToolObservationReused,
    ToolPolicyChecked,
)
from allCode.core.models import ToolCall, ToolResult, TurnInput, TurnState
from allCode.core.result import CompletionEvidence
from allCode.tools.approval import ApprovalManager
from allCode.tools.base import ToolContext
from allCode.tools.executor import ToolExecutor
from allCode.tools.registry import ToolRegistry


class ToolCallProcessor:
    """Executes model-selected tool calls through standard allCode contracts."""

    def __init__(
        self,
        *,
        tools: ToolRegistry,
        event_bus: EventBus,
        tool_policy: ToolPolicy,
        approval: ApprovalManager,
        tool_executor: ToolExecutor,
        target_recorder: ToolTargetRecorder,
        observation_cache: ObservationCache | None = None,
        tool_budget: ToolBudgetTracker | None = None,
        patch_failures: PatchFailureTracker | None = None,
        action_ledger: ToolActionLedger | None = None,
    ) -> None:
        self._tools = tools
        self._event_bus = event_bus
        self._tool_policy = tool_policy
        self._approval = approval
        self._tool_executor = tool_executor
        self._target_recorder = target_recorder
        self._observation_cache = observation_cache or ObservationCache()
        self._tool_budget = tool_budget or ToolBudgetTracker()
        self._patch_failures = patch_failures or PatchFailureTracker()
        self._action_ledger = action_ledger or ToolActionLedger()
        self._evidence_recorder = ToolEvidenceRecorder()
        self._schema_filter = ToolSchemaFilter(registry=tools, policy=tool_policy)

    async def execute(
        self,
        turn_input: TurnInput,
        state: TurnState,
        tool_calls: Sequence[ToolCall],
        loop_guard: ToolLoopGuard,
        recovery: RecoveryTracker,
        completion_evidence: CompletionEvidence,
        routing,
        *,
        allowed_tool_names: set[str] | None = None,
        phase_gate: PhaseToolGate | None = None,
        inspect_stage=None,
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        self._tool_budget.reset_for_turn(state.turn_id)
        self._patch_failures.reset_for_turn(state.turn_id)
        context = ToolContext(
            workspace=turn_input.workspace,
            session_id=turn_input.session_id,
            turn_id=state.turn_id,
            approval_mode=self._approval.mode,
            user_prompt=turn_input.user_prompt,
        )
        for tool_call in tool_calls:
            tool_call = normalize_tool_call_for_routing(tool_call, routing)
            tool_call = normalize_inspect_stage_call(tool_call, inspect_stage)
            self._action_ledger.record(tool_call, "requested")
            tool = self._tools.get(tool_call.name)
            if tool is not None:
                tool_call = strip_harmless_extra_arguments(tool_call, tool.definition)
            read_only_denial = read_only_tool_denial(
                routing=routing,
                tool_call=tool_call,
                policy=self._tool_policy,
                definition=tool.definition if tool is not None else None,
            )
            if read_only_denial is not None:
                self._action_ledger.record(tool_call, "policy_denied")
                if tool_call.name not in completion_evidence.policy_denied_tools:
                    completion_evidence.policy_denied_tools.append(tool_call.name)
                results.append(read_only_denial)
                continue
            if allowed_tool_names is not None and tool_call.name not in allowed_tool_names:
                self._action_ledger.record(tool_call, "schema_denied")
                reason = f"Tool {tool_call.name} is not in the allowed schema for this round."
                results.append(
                    await deny_tool_schema(
                        event_bus=self._event_bus,
                        turn_id=state.turn_id,
                        tool_call=tool_call,
                        policy=self._tool_policy,
                        allowed_tool_names=allowed_tool_names,
                        phase_gate=phase_gate,
                        reason=reason,
                    )
                )
                continue
            target_denial = phase_target_denial(
                tool_call,
                phase_gate=phase_gate,
                inspect_stage=inspect_stage,
                workspace_root=turn_input.workspace.root,
            )
            if target_denial is not None:
                self._action_ledger.record(tool_call, "schema_denied")
                results.append(
                    await deny_tool_schema(
                        event_bus=self._event_bus,
                        turn_id=state.turn_id,
                        tool_call=tool_call,
                        policy=self._tool_policy,
                        allowed_tool_names=allowed_tool_names,
                        phase_gate=phase_gate,
                        reason=target_denial,
                    )
                )
                continue
            else:
                policy_decision = self._tool_policy.check(
                    routing=routing,
                    tool_call=tool_call,
                    definition=tool.definition if tool is not None else None,
                )
            if tool is not None:
                schema_error = validate_tool_arguments(tool_call, tool.definition)
                if schema_error:
                    self._action_ledger.record(tool_call, "schema_denied")
                    results.append(
                        await deny_tool_schema(
                            event_bus=self._event_bus,
                            turn_id=state.turn_id,
                            tool_call=tool_call,
                            policy=self._tool_policy,
                            allowed_tool_names=allowed_tool_names,
                            phase_gate=phase_gate,
                            reason=schema_error,
                        )
                    )
                    continue
            await self._event_bus.publish(
                ToolPolicyChecked(
                    turn_id=state.turn_id,
                    message=f"Tool policy checked: {tool_call.name}.",
                    data={
                        "tool_call": tool_call.model_dump(mode="json"),
                        "allowed": policy_decision.allowed,
                        "reason": policy_decision.reason,
                        "category": policy_decision.category,
                    },
                )
            )
            if not policy_decision.allowed:
                self._action_ledger.record(tool_call, "policy_denied")
                if tool_call.name not in completion_evidence.policy_denied_tools:
                    completion_evidence.policy_denied_tools.append(tool_call.name)
                results.append(policy_denied_tool_result(tool_call, policy_decision))
                continue
            cached_result = self._observation_cache.get(tool_call, workspace_root=turn_input.workspace.root)
            if cached_result is not None:
                self._action_ledger.record(tool_call, "reused")
                await self._event_bus.publish(
                    ToolObservationReused(
                        turn_id=state.turn_id,
                        message=f"Tool observation reused: {tool_call.name}.",
                        tool_call=tool_call,
                        data={
                            "tool_name": tool_call.name,
                            "cached": True,
                            "cache_key": cached_result.metadata.get("cache_key"),
                        },
                    )
                )
                self._target_recorder.record(state, cached_result)
                results.append(cached_result)
                continue

            patch_strategy = self._patch_failures.repeated_failure(
                tool_call,
                workspace_root=turn_input.workspace.root,
            )
            if patch_strategy is not None:
                self._action_ledger.record(tool_call, "suppressed")
                await self._record_recovery(
                    state,
                    recovery,
                    "no_progress",
                    attempts=int(patch_strategy.metadata.get("repeat_count") or 1),
                    last_error=patch_strategy.error,
                    blocked=True,
                )
                await self._event_bus.publish(
                    ToolCallSuppressed(
                        turn_id=state.turn_id,
                        message=f"Patch strategy required before retry: {tool_call.name}.",
                        tool_call=tool_call,
                        data=patch_strategy.metadata,
                    )
                )
                results.append(patch_strategy)
                continue

            budget_decision = self._tool_budget.check(tool_call, workspace_root=turn_input.workspace.root)
            if not budget_decision.allowed:
                self._action_ledger.record(tool_call, "suppressed")
                suppressed = suppressed_tool_result(
                    tool_call,
                    reason=budget_decision.reason,
                    count=budget_decision.count,
                )
                await self._record_recovery(
                    state,
                    recovery,
                    "no_progress",
                    attempts=budget_decision.count,
                    last_error=budget_decision.reason,
                    blocked=True,
                )
                await self._event_bus.publish(
                    ToolCallSuppressed(
                        turn_id=state.turn_id,
                        message=f"Tool call suppressed: {tool_call.name}.",
                        tool_call=tool_call,
                        data={
                            "reason": budget_decision.reason,
                            "count": budget_decision.count,
                        },
                    )
                )
                await self._event_bus.publish(
                    ToolLoopDetected(
                        turn_id=state.turn_id,
                        message="Repeated tool target suppressed by budget guard.",
                        tool_call=tool_call,
                        data={
                            "budget_guard": True,
                            "reason": budget_decision.reason,
                            "count": budget_decision.count,
                        },
                    )
                )
                results.append(suppressed)
                continue
            signature, loop_detected = loop_guard.record(tool_call)
            if signature.count == 2 and not loop_detected:
                await self._record_recovery(
                    state,
                    recovery,
                    "tool_loop",
                    attempts=signature.count,
                    last_error="same tool target repeated; ask the model to use existing observations before repeating",
                )
            if loop_detected:
                self._action_ledger.record(tool_call, "suppressed")
                await self._record_recovery(state, recovery, "tool_loop", attempts=signature.count, blocked=True)
                await self._event_bus.publish(
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
            if policy_decision.allowed:
                self._action_ledger.record(tool_call, "executed")
                state.tool_calls.append(tool_call)
                await self._event_bus.publish(
                    ToolCallRequested(
                        turn_id=state.turn_id,
                        message=f"Tool requested: {tool_call.name}",
                        tool_call=tool_call,
                    )
                )

            result = await self._tool_executor.execute(
                tool_call,
                context,
                routing=routing,
                completion_evidence=completion_evidence,
                event_bus=self._event_bus,
            )
            result = attach_validation_failure_summary(result)
            self._evidence_recorder.record(
                result,
                completion_evidence,
                workspace_root=turn_input.workspace.root,
            )
            self._patch_failures.record_result(tool_call, result, workspace_root=turn_input.workspace.root)
            self._observation_cache.invalidate_from_result(result)
            self._tool_budget.reset_for_mutation_attempt(result)
            if result.name in {"write_file", "patch_file", "delete_path"} and result.ok:
                loop_guard.reset_after_mutation()
            self._observation_cache.store(tool_call, result, workspace_root=turn_input.workspace.root)
            self._target_recorder.record(state, result)
            results.append(result)
            observation_count, observation_loop, observation_reason = loop_guard.record_observation(tool_call, result)
            if observation_loop:
                await self._record_recovery(
                    state,
                    recovery,
                    "no_progress",
                    attempts=observation_count,
                    last_error=f"{observation_reason}: {tool_call.name}",
                    blocked=True,
                )
                await self._event_bus.publish(
                    ToolLoopDetected(
                        turn_id=state.turn_id,
                        message="Repeated tool action-observation pattern detected.",
                        tool_call=tool_call,
                        data={
                            "observation_loop": True,
                            "reason": observation_reason,
                            "count": observation_count,
                            "result_ok": result.ok,
                            "error_type": result.error_type,
                        },
                    )
                )
                results.append(
                    ToolResult(
                        call_id=tool_call.id,
                        name=tool_call.name,
                        ok=False,
                        error=f"Repeated {observation_reason} blocked by loop guard.",
                        error_type="no_progress_detected",
                    )
                )
        return results

    def tool_schemas_for_routing(self, routing, **kwargs):
        return self._schema_filter.schemas_for_routing(routing, **kwargs)

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
        await self._event_bus.publish(
            RecoveryStateUpdated(
                turn_id=state.turn_id,
                message=f"Recovery state updated: {latest.reason}.",
                data=latest.model_dump(mode="json"),
            )
        )

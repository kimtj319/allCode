"""Tool-call policy, loop guarding, execution, and schema filtering."""

from __future__ import annotations

from collections.abc import Sequence

from allCode.agent.policy import ToolPolicy
from allCode.agent.phase_gate import PhaseToolGate
from allCode.agent.recovery import RecoveryTracker, ToolLoopGuard
from allCode.agent.tool_action_ledger import ToolActionLedger
from allCode.agent.tool_targets import ToolTargetRecorder
from allCode.core.event_bus import EventBus
from allCode.agent.tool_orchestrator import ObservationCache, ToolBudgetTracker, suppressed_tool_result
from allCode.agent.validation_repair import attach_validation_failure_summary
from allCode.core.events import (
    RecoveryStateUpdated,
    ToolCallRequested,
    ToolCallSchemaDenied,
    ToolCallSuppressed,
    ToolLoopDetected,
    ToolObservationReused,
    ToolPolicyChecked,
)
from allCode.core.models import ToolCall, ToolResult, TurnInput, TurnState
from allCode.core.result import CompletionEvidence
from allCode.llm.settings import ToolSchema
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
        self._action_ledger = action_ledger or ToolActionLedger()

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
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        self._tool_budget.reset_for_turn(state.turn_id)
        context = ToolContext(
            workspace=turn_input.workspace,
            session_id=turn_input.session_id,
            turn_id=state.turn_id,
            approval_mode=self._approval.mode,
        )
        for tool_call in tool_calls:
            tool_call = self._normalize_tool_call_for_routing(tool_call, routing)
            self._action_ledger.record(tool_call, "requested")
            tool = self._tools.get(tool_call.name)
            if allowed_tool_names is not None and tool_call.name not in allowed_tool_names:
                self._action_ledger.record(tool_call, "schema_denied")
                next_action = phase_gate.required_next_action if phase_gate is not None else ""
                phase_reason = phase_gate.reason if phase_gate is not None else ""
                reason = f"Tool {tool_call.name} is not in the allowed schema for this round."
                if next_action:
                    reason = f"{reason} Required next action: {next_action}"
                await self._event_bus.publish(
                    ToolCallSchemaDenied(
                        turn_id=state.turn_id,
                        message=f"Tool schema denied: {tool_call.name}.",
                        tool_call=tool_call,
                        data={
                            "tool_name": tool_call.name,
                            "allowed_tools": sorted(allowed_tool_names),
                            "reason": reason,
                            "phase": phase_gate.phase if phase_gate is not None else None,
                            "phase_reason": phase_reason,
                            "required_next_action": next_action,
                            "category": self._tool_policy.category_for_tool(tool_call.name),
                        },
                    )
                )
                results.append(
                    ToolResult(
                        call_id=tool_call.id,
                        name=tool_call.name,
                        ok=False,
                        error=reason,
                        error_type="schema_denied",
                        metadata={
                            "category": self._tool_policy.category_for_tool(tool_call.name),
                            "allowed_tools": sorted(allowed_tool_names),
                            "phase": phase_gate.phase if phase_gate is not None else None,
                            "phase_reason": phase_reason,
                            "required_next_action": next_action,
                            "observation": {
                                "kind": "schema_denied",
                                "target": tool_call.name,
                                "summary": reason,
                                "risk": "low",
                            },
                        },
                    )
                )
                continue
            else:
                policy_decision = self._tool_policy.check(
                    routing=routing,
                    tool_call=tool_call,
                    definition=tool.definition if tool is not None else None,
                )
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
                results.append(
                    ToolResult(
                        call_id=tool_call.id,
                        name=tool_call.name,
                        ok=False,
                        error=policy_decision.reason,
                        error_type="policy_denied",
                        metadata={
                            "category": policy_decision.category,
                            "observation": {
                                "kind": "policy_denied",
                                "target": tool_call.name,
                                "summary": policy_decision.reason,
                                "risk": "medium",
                            },
                        },
                    )
                )
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
            self._record_validation_failure_symbols(result, completion_evidence)
            self._observation_cache.invalidate_from_result(result)
            self._tool_budget.reset_for_mutation_attempt(result)
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

    def tool_schemas_for_routing(
        self,
        routing,
        *,
        suppress_validation: bool = False,
        only_mutation: bool = False,
        only_validation: bool = False,
        include_validation_probe: bool = False,
        allowed_only: set[str] | None = None,
    ) -> list[ToolSchema]:
        definitions = self._tools.definitions()
        allowed_names = self._tool_policy.allowed_registered_tool_names(routing, definitions)
        if suppress_validation:
            allowed_names = {name for name in allowed_names if name != "run_tests"}
        if only_mutation:
            mutation_names = {"patch_file", "write_file"}
            if include_validation_probe:
                mutation_names.add("run_tests")
            allowed_names = {name for name in allowed_names if name in mutation_names}
        if only_validation:
            allowed_names = {name for name in allowed_names if name == "run_tests"}
        if allowed_only is not None:
            allowed_names = {name for name in allowed_names if name in allowed_only}
        return [
            ToolSchema(
                name=definition.name,
                description=definition.description,
                parameters=definition.parameters,
            )
            for definition in definitions
            if definition.name in allowed_names
        ]

    def _normalize_tool_call_for_routing(self, tool_call: ToolCall, routing) -> ToolCall:
        if tool_call.name in {"run_validation", "run_test"} and routing.requires_validation:
            return tool_call.model_copy(update={"name": "run_tests"})
        if tool_call.name != "run_command" or not routing.requires_validation:
            return tool_call
        command = str(tool_call.arguments.get("command", "")).strip().lower()
        if not self._looks_like_validation_command(command):
            return tool_call
        return tool_call.model_copy(update={"name": "run_tests"})

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

    @staticmethod
    def _looks_like_validation_command(command: str) -> bool:
        validation_markers = (
            "pytest",
            "python -m pytest",
            "unittest",
            "npm test",
            "npm run test",
            "cargo test",
            "go test",
            "gradle test",
            "./gradlew test",
            "mvn test",
        )
        return any(marker in command for marker in validation_markers)

    @staticmethod
    def _record_validation_failure_symbols(result: ToolResult, evidence: CompletionEvidence) -> None:
        failure = result.metadata.get("validation_failure")
        if not isinstance(failure, dict):
            return
        for symbol in failure.get("failing_symbols", []):
            if isinstance(symbol, str) and symbol and symbol not in evidence.validation_failure_symbols:
                evidence.validation_failure_symbols.append(symbol)

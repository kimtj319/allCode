"""Policy, approval, execution, and evidence updates for tools."""

from __future__ import annotations

import time
from pathlib import Path

from allCode.agent.policy import ToolPolicy
from allCode.agent.read_only_guard import read_only_tool_denial
from allCode.agent.router import RoutingDecision
from allCode.core.event_bus import EventBus
from allCode.core.events import (
    ApprovalRequested,
    ApprovalResolved,
    EmptySearchDenied,
    SourceOverviewCollected,
    ToolApprovalChecked,
    ToolExecutionFinished,
    ToolExecutionStarted,
    ValidationFinished,
    ValidationStarted,
)
from allCode.core.models import ToolCall, ToolResult
from allCode.core.result import CompletionEvidence
from allCode.tools.approval import ApprovalDecision, ApprovalHandler, ApprovalManager, ApprovalRequest
from allCode.tools.approval_preview import ApprovalPreview, build_command_preview, build_diff_preview
from allCode.tools.base import ToolContext
from allCode.tools.builtin.file_ops import PatchApplicationError, apply_exact_patches, read_text_if_exists, resolve_under_root
from allCode.tools.diff import EditTransaction
from allCode.tools.executor_evidence import update_completion_evidence
from allCode.tools.registry import ToolRegistry

class ToolExecutor:
    """Runs registered tools after route policy and approval checks."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy: ToolPolicy | None = None,
        approval: ApprovalManager | None = None,
        approval_handler: ApprovalHandler | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy or ToolPolicy()
        self._approval = approval or ApprovalManager()
        self._approval_handler = approval_handler

    @property
    def approval_mode(self) -> str:
        return self._approval.mode

    async def execute(
        self,
        call: ToolCall,
        context: ToolContext,
        *,
        routing: RoutingDecision | None = None,
        completion_evidence: CompletionEvidence | None = None,
        event_bus: EventBus | None = None,
    ) -> ToolResult:
        started = time.perf_counter()
        tool = self._registry.get(call.name)
        turn_id = context.turn_id or call.id
        if tool is None:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=f"Tool is not registered: {call.name}", error_type="tool_not_found")

        definition = tool.definition
        read_only_denial = read_only_tool_denial(
            routing=routing,
            tool_call=call,
            policy=self._policy,
            definition=definition,
        )
        if read_only_denial is not None:
            if completion_evidence is not None and call.name not in completion_evidence.policy_denied_tools:
                completion_evidence.policy_denied_tools.append(call.name)
            return read_only_denial
        destructive = self._is_destructive(call)
        policy_decision = self._policy.check(routing=routing, tool_call=call, definition=definition, destructive=destructive)
        if not policy_decision.allowed:
            if completion_evidence is not None and call.name not in completion_evidence.policy_denied_tools:
                completion_evidence.policy_denied_tools.append(call.name)
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=policy_decision.reason,
                error_type="policy_denied",
                metadata={
                    "category": policy_decision.category,
                    "observation": {
                        "kind": "policy_denied",
                        "target": call.name,
                        "summary": policy_decision.reason,
                        "risk": "medium",
                    },
                },
            )

        approval_result = await self._check_approval(call, context, event_bus, turn_id)
        if approval_result is not None:
            return approval_result

        try:
            if call.name == "run_tests" and event_bus is not None:
                await event_bus.publish(ValidationStarted(turn_id=turn_id, message="Validation started.", data={"command": call.arguments.get("command", "")}))
            if event_bus is not None:
                await event_bus.publish(ToolExecutionStarted(turn_id=turn_id, message=f"Tool execution started: {call.name}", tool_call=call))
            result = await tool.run(call, context, event_bus)
        except Exception as exc:
            result = ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        metadata = dict(result.metadata)
        metadata["duration_ms"] = elapsed_ms
        result = result.model_copy(update={"metadata": metadata})
        if completion_evidence is not None:
            update_completion_evidence(result, completion_evidence, workspace_root=context.workspace.root)
        if call.name == "run_tests" and event_bus is not None:
            await event_bus.publish(
                ValidationFinished(
                    turn_id=turn_id,
                    message="Validation finished.",
                    data={
                        "command": call.arguments.get("command", ""),
                        "passed": result.metadata.get("validation_passed"),
                    },
                )
            )
        if event_bus is not None:
            await event_bus.publish(ToolExecutionFinished(turn_id=turn_id, message=f"Tool execution finished: {call.name}", result=result))
            await self._publish_tool_observation_event(event_bus, turn_id=turn_id, result=result)
        return result

    async def _publish_tool_observation_event(self, event_bus: EventBus, *, turn_id: str, result: ToolResult) -> None:
        if result.name == "source_overview" and result.ok:
            await event_bus.publish(
                SourceOverviewCollected(
                    turn_id=turn_id,
                    message="Source overview collected.",
                    data={
                        "target": _observation_target(result),
                        "file_count": result.metadata.get("file_count"),
                        "symbol_count": result.metadata.get("symbol_count"),
                        "truncated": bool(result.metadata.get("truncated")),
                        "overview_paths": list(result.metadata.get("source_overview_paths") or result.metadata.get("overview_paths") or []),
                        "suggested_reads": list(result.metadata.get("suggested_reads") or []),
                        "representative_reads": list(result.metadata.get("representative_reads") or []),
                        "package_roles": list(result.metadata.get("package_roles") or []),
                        "coverage": dict(result.metadata.get("coverage") or {}),
                    },
                )
            )
        if result.name == "search_files" and (result.metadata.get("invalid_query") or result.error_type == "invalid_query"):
            await event_bus.publish(
                EmptySearchDenied(
                    turn_id=turn_id,
                    message="Empty search query denied.",
                    data={
                        "target": _observation_target(result),
                        "required_next_action": result.metadata.get("required_next_action"),
                    },
                )
            )

    async def _check_approval(
        self,
        call: ToolCall,
        context: ToolContext,
        event_bus: EventBus | None,
        turn_id: str,
    ) -> ToolResult | None:
        decision = None
        if call.name in {"write_file", "patch_file", "delete_path"}:
            if call.name == "delete_path" and call.arguments.get("missing_ok"):
                delete_arg = call.arguments.get("path", call.arguments.get("file_path", ""))
                try:
                    path = resolve_under_root(context.workspace.root, str(delete_arg))
                except Exception as exc:
                    return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)
                if not Path(path).exists():
                    return None
            preview = self._file_preview(call, context)
            if isinstance(preview, ToolResult):
                return preview
            approval_preview = build_diff_preview(
                preview,
                target=self._target_for_call(call, context),
                action=call.name,
            )
            decision = self._with_approval_preview(
                self._approval.file_mutation(preview=approval_preview.preview, tool_name=call.name),
                approval_preview,
            )
        elif call.name in {"run_command", "run_tests"}:
            command = str(call.arguments.get("command", ""))
            decision = self._with_approval_preview(
                self._approval.shell_command(command, validation=call.name == "run_tests"),
                build_command_preview(command, validation=call.name == "run_tests"),
            )

        if decision is None or decision.allowed:
            if decision is not None and event_bus is not None:
                await event_bus.publish(
                    ToolApprovalChecked(
                        turn_id=turn_id,
                        message=f"Tool approval checked: {call.name}.",
                        data={
                            "tool_name": call.name,
                            "allowed": decision.allowed,
                            "reason": decision.reason,
                            "mode": context.approval_mode,
                            "approval_preview": decision.metadata.get("approval_preview"),
                        },
                    )
                )
                await event_bus.publish(ApprovalResolved(turn_id=turn_id, message=decision.reason, data=decision.model_dump(mode="json")))
            return None

        if event_bus is not None:
            await event_bus.publish(
                ToolApprovalChecked(
                    turn_id=turn_id,
                    message=f"Tool approval checked: {call.name}.",
                        data={
                            "tool_name": call.name,
                            "allowed": decision.allowed,
                            "reason": decision.reason,
                            "mode": context.approval_mode,
                            "approval_preview": decision.metadata.get("approval_preview"),
                        },
                    )
                )
            await event_bus.publish(ApprovalRequested(turn_id=turn_id, message=decision.reason, data=decision.model_dump(mode="json")))
        if self._approval_handler is not None:
            action = await self._approval_handler(
                ApprovalRequest(
                    approval_id=decision.approval_id,
                    tool_name=call.name,
                    decision=decision,
                    preview=decision.preview,
                    risk=decision.risk,
                    call=call,
                )
            )
            if action in {"approve_once", "allow_session"}:
                if action == "allow_session":
                    self._approval.allow_for_session(self._session_rule_for_call(call))
                resolved = decision.model_copy(
                    update={
                        "allowed": True,
                        "requires_approval": False,
                        "reason": "Approved by interactive user input.",
                    }
                )
                if event_bus is not None:
                    await event_bus.publish(
                        ApprovalResolved(
                            turn_id=turn_id,
                            message=resolved.reason,
                            data={**resolved.model_dump(mode="json"), "action": action},
                        )
                    )
                return None
            if event_bus is not None:
                await event_bus.publish(
                    ApprovalResolved(
                        turn_id=turn_id,
                        message="Approval denied by user.",
                        data={**decision.model_dump(mode="json"), "action": action},
                    )
                )
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error="Approval denied by user.",
                error_type="approval_denied",
                metadata={"approval": {**decision.model_dump(mode="json"), "action": action}},
            )
        if event_bus is not None:
            await event_bus.publish(ApprovalResolved(turn_id=turn_id, message="Approval denied or unavailable.", data=decision.model_dump(mode="json")))
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=False,
            error=decision.reason,
            error_type="approval_required",
            metadata={"approval": decision.model_dump(mode="json")},
        )

    def _file_preview(self, call: ToolCall, context: ToolContext) -> str | ToolResult:
        try:
            if call.name == "write_file":
                path = resolve_under_root(context.workspace.root, str(call.arguments["file_path"]))
                before = read_text_if_exists(path)
                after = str(call.arguments["content"])
                action = "created" if not Path(path).exists() else "modified"
            elif call.name == "patch_file":
                path = resolve_under_root(context.workspace.root, str(call.arguments["file_path"]))
                before = read_text_if_exists(path)
                after = self._preview_patch(before, call.arguments.get("patches", []))
                action = "modified"
            else:
                delete_arg = call.arguments.get("path", call.arguments.get("file_path", ""))
                path = resolve_under_root(context.workspace.root, str(delete_arg))
                before = read_text_if_exists(path) if Path(path).is_file() else ""
                after = ""
                action = "deleted"
            return EditTransaction.from_contents(path=path, before=before, after=after, action=action).diff
        except PatchApplicationError as exc:
            path_arg = str(call.arguments.get("file_path") or call.arguments.get("path") or "")
            try:
                path_arg = str(resolve_under_root(context.workspace.root, path_arg))
            except Exception:
                pass
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=str(exc),
                error_type=exc.error_type,
                metadata=exc.metadata(file_path=path_arg),
            )
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)

    def _preview_patch(self, content: str, patches) -> str:
        return apply_exact_patches(content, patches)

    def _is_destructive(self, call: ToolCall) -> bool:
        if call.name in {"write_file", "patch_file", "delete_path"}:
            return True
        if call.name in {"run_command", "run_tests"}:
            return self._approval.is_destructive_command(str(call.arguments.get("command", "")))
        return False

    def _session_rule_for_call(self, call: ToolCall) -> str:
        if call.name in {"write_file", "patch_file", "delete_path"}:
            return call.name
        if call.name in {"run_command", "run_tests"}:
            command = str(call.arguments.get("command", "")).strip()
            return command or call.name
        return call.name

    def _target_for_call(self, call: ToolCall, context: ToolContext) -> str:
        path_arg = str(call.arguments.get("file_path") or call.arguments.get("path") or "")
        if not path_arg:
            return call.name
        try:
            path = resolve_under_root(context.workspace.root, path_arg)
            return str(Path(path).relative_to(context.workspace.root))
        except Exception:
            return path_arg

    @staticmethod
    def _with_approval_preview(decision: "ApprovalDecision", preview: ApprovalPreview) -> "ApprovalDecision":
        metadata = dict(decision.metadata)
        metadata["approval_preview"] = preview.model_dump(mode="json")
        return decision.model_copy(update={"metadata": metadata, "preview": preview.preview})

def _observation_target(result: ToolResult) -> str:
    observation = result.metadata.get("observation")
    if isinstance(observation, dict):
        target = observation.get("target")
        if isinstance(target, str) and target:
            return target
    for key in ("path", "file_path", "query", "command"):
        value = result.metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return result.name

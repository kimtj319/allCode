"""Policy, approval, execution, and evidence updates for tools."""

from __future__ import annotations

import time
from pathlib import Path

from allCode.agent.policy import ToolPolicy
from allCode.agent.router import RoutingDecision
from allCode.core.event_bus import EventBus
from allCode.core.events import (
    ApprovalRequested,
    ApprovalResolved,
    ToolExecutionFinished,
    ToolExecutionStarted,
    ValidationFinished,
    ValidationStarted,
)
from allCode.core.models import ToolCall, ToolResult
from allCode.core.result import CompletionEvidence
from allCode.tools.approval import ApprovalManager
from allCode.tools.base import ToolContext
from allCode.tools.builtin.file_ops import read_text_if_exists, resolve_under_root
from allCode.tools.diff import EditTransaction
from allCode.tools.registry import ToolRegistry


class ToolExecutor:
    """Runs registered tools after route policy and approval checks."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy: ToolPolicy | None = None,
        approval: ApprovalManager | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy or ToolPolicy()
        self._approval = approval or ApprovalManager()

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
        destructive = self._is_destructive(call)
        policy_decision = self._policy.check(routing=routing, tool_call=call, definition=definition, destructive=destructive)
        if not policy_decision.allowed:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=policy_decision.reason,
                error_type="policy_denied",
                metadata={"category": policy_decision.category},
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
            self._update_completion_evidence(result, completion_evidence)
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
        return result

    async def _check_approval(
        self,
        call: ToolCall,
        context: ToolContext,
        event_bus: EventBus | None,
        turn_id: str,
    ) -> ToolResult | None:
        decision = None
        if call.name in {"write_file", "patch_file"}:
            preview = self._file_preview(call, context)
            if isinstance(preview, ToolResult):
                return preview
            decision = self._approval.file_mutation(preview=preview, tool_name=call.name)
        elif call.name in {"run_command", "run_tests"}:
            decision = self._approval.shell_command(str(call.arguments.get("command", "")), validation=call.name == "run_tests")

        if decision is None or decision.allowed:
            if decision is not None and event_bus is not None:
                await event_bus.publish(ApprovalResolved(turn_id=turn_id, message=decision.reason, data=decision.model_dump(mode="json")))
            return None

        if event_bus is not None:
            await event_bus.publish(ApprovalRequested(turn_id=turn_id, message=decision.reason, data=decision.model_dump(mode="json")))
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
            path = resolve_under_root(context.workspace.root, str(call.arguments["file_path"]))
            before = read_text_if_exists(path)
            if call.name == "write_file":
                after = str(call.arguments["content"])
                action = "created" if not Path(path).exists() else "modified"
            else:
                after = self._preview_patch(before, call.arguments.get("patches", []))
                action = "modified"
            return EditTransaction.from_contents(path=path, before=before, after=after, action=action).diff
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)

    def _preview_patch(self, content: str, patches) -> str:
        if not isinstance(patches, list) or not patches:
            raise ValueError("patches must be a non-empty list")
        updated = content
        for patch in patches:
            if not isinstance(patch, dict):
                raise ValueError("each patch must be an object")
            search = str(patch.get("search", ""))
            replace = str(patch.get("replace", ""))
            count = updated.count(search)
            if count != 1:
                raise ValueError(f"patch search must match exactly once, matched {count} times")
            updated = updated.replace(search, replace, 1)
        return updated

    def _is_destructive(self, call: ToolCall) -> bool:
        if call.name in {"write_file", "patch_file"}:
            return True
        if call.name in {"run_command", "run_tests"}:
            return self._approval.is_destructive_command(str(call.arguments.get("command", "")))
        return False

    def _update_completion_evidence(self, result: ToolResult, evidence: CompletionEvidence) -> None:
        command = result.metadata.get("command")
        if result.metadata.get("validation_command") and isinstance(command, str):
            if command not in evidence.validation_commands:
                evidence.validation_commands.append(command)
            evidence.validation_passed = bool(result.metadata.get("validation_passed"))
            if evidence.validation_passed is True:
                evidence.status = "validated"
        if not result.ok:
            return
        created = [str(path) for path in result.metadata.get("created_files", [])]
        changed = [str(path) for path in result.metadata.get("changed_files", [])]
        for path in created:
            if path not in evidence.created_files:
                evidence.created_files.append(path)
        for path in changed:
            if path not in evidence.changed_files:
                evidence.changed_files.append(path)
        if evidence.validation_passed is True:
            evidence.status = "validated"
        elif evidence.has_file_change():
            evidence.status = "changed"

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
    ToolApprovalChecked,
    ToolExecutionFinished,
    ToolExecutionStarted,
    ValidationFinished,
    ValidationStarted,
)
from allCode.core.models import ToolCall, ToolResult
from allCode.core.result import CompletionEvidence, DocumentManifest
from allCode.tools.approval import ApprovalManager
from allCode.tools.base import ToolContext
from allCode.tools.builtin.file_ops import PatchApplicationError, apply_exact_patches, read_text_if_exists, resolve_under_root
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
            decision = self._approval.file_mutation(preview=preview, tool_name=call.name)
        elif call.name in {"run_command", "run_tests"}:
            decision = self._approval.shell_command(str(call.arguments.get("command", "")), validation=call.name == "run_tests")

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
                    },
                )
            )
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

    def _update_completion_evidence(self, result: ToolResult, evidence: CompletionEvidence) -> None:
        if result.name == "search_files":
            query = str(result.metadata.get("query") or result.metadata.get("search_query") or "")
            if not query:
                observation = result.metadata.get("observation")
                if isinstance(observation, dict):
                    query = str(observation.get("query") or "")
            if result.metadata.get("evidence_count") == 0:
                fallback_query = query or _search_query_from_content(result.content)
                if fallback_query and fallback_query not in evidence.zero_result_queries:
                    evidence.zero_result_queries.append(fallback_query)
            for match in result.metadata.get("matches", []):
                if not isinstance(match, dict):
                    continue
                path = str(match.get("path") or "")
                if path and path not in evidence.search_candidate_paths:
                    evidence.search_candidate_paths.append(path)
        if result.name == "read_file":
            path = str(result.metadata.get("file_path") or "")
            if path and path not in evidence.inspected_paths:
                evidence.inspected_paths.append(path)
            if result.error_type == "not_found" and path and path not in evidence.not_found_targets:
                evidence.not_found_targets.append(path)
        if result.name == "web_search" and result.error_type == "web_search_unavailable":
            query = str(result.metadata.get("query") or "")
            if query and query not in evidence.web_unavailable_queries:
                evidence.web_unavailable_queries.append(query)
        command = result.metadata.get("command")
        if result.metadata.get("validation_command") and isinstance(command, str):
            if command not in evidence.validation_commands:
                evidence.validation_commands.append(command)
            evidence.validation_passed = bool(result.metadata.get("validation_passed"))
            failure = result.metadata.get("validation_failure")
            if isinstance(failure, dict):
                for symbol in failure.get("failing_symbols", []):
                    if isinstance(symbol, str) and symbol and symbol not in evidence.validation_failure_symbols:
                        evidence.validation_failure_symbols.append(symbol)
            if evidence.validation_passed is True:
                evidence.status = "validated"
        if not result.ok:
            return
        noop_targets = [str(path) for path in result.metadata.get("noop_targets", [])]
        if result.metadata.get("safe_noop"):
            evidence.safe_noop = True
            evidence.noop_reason = str(result.metadata.get("noop_reason") or result.error_type or "safe_noop")
            for path in noop_targets:
                if path not in evidence.noop_targets:
                    evidence.noop_targets.append(path)
        created = [str(path) for path in result.metadata.get("created_files", [])]
        changed = [str(path) for path in result.metadata.get("changed_files", [])]
        deleted = [str(path) for path in result.metadata.get("deleted_files", [])]
        for path in created:
            if path not in evidence.created_files:
                evidence.created_files.append(path)
        for path in changed:
            if path not in evidence.changed_files:
                evidence.changed_files.append(path)
        for path in deleted:
            if path not in evidence.deleted_files:
                evidence.deleted_files.append(path)
        document_manifest = _document_manifest_from_paths([*created, *changed], turn_id="")
        if document_manifest is not None:
            evidence.document_manifest = document_manifest
        if evidence.validation_passed is True:
            evidence.status = "validated"
        elif evidence.has_resolution_evidence():
            evidence.status = "changed"


def _search_query_from_content(content: str) -> str:
    marker = "No matches found for query "
    if marker not in content:
        return ""
    tail = content.split(marker, 1)[1]
    if not tail:
        return ""
    quote = tail[0]
    if quote not in {"'", '"'}:
        return tail.split(" ", 1)[0].strip(". ")
    return tail[1:].split(quote, 1)[0].strip()


def _document_manifest_from_paths(paths: list[str], *, turn_id: str) -> DocumentManifest | None:
    for raw_path in reversed(paths):
        path = Path(raw_path)
        if path.suffix.lower() not in {".md", ".txt", ".rst"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        headings = _document_headings(content)
        title = headings[0] if headings else path.stem.replace("_", " ").replace("-", " ").strip()
        return DocumentManifest(
            path=str(path),
            title=title,
            artifact_kind="markdown" if path.suffix.lower() == ".md" else "text",
            section_headings=headings[:20],
            updated_at_turn_id=turn_id,
        )
    return None


def _document_headings(content: str) -> list[str]:
    headings: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title and title not in headings:
                headings.append(title)
        if len(headings) >= 20:
            break
    return headings

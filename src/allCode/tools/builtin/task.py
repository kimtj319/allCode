"""Sub-agent (task delegation) tool.

Runs a focused, read-only inspection turn in a nested AgentLoop and returns its
answer. The sub-agent gets only inspection tools (no mutation, no shell, no
``task`` itself), so delegation is depth-1 and side-effect free — a safe way to
fan a self-contained research question off the main turn.
"""

from __future__ import annotations

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition

_INSPECTION_TOOLS = {
    "read_file",
    "search_files",
    "list_directory",
    "list_tree",
    "glob_files",
    "source_overview",
    "source_probe",
}


class TaskTool:
    definition = ToolDefinition(
        name="task",
        description=(
            "Delegate a self-contained, read-only research/analysis question to a sub-agent. "
            "The sub-agent can read, search, and probe the workspace but cannot modify files or "
            "run commands. Returns its findings as text. Use for scoped investigations."
        ),
        parameters={
            "type": "object",
            "properties": {"description": {"type": "string", "description": "The subtask to investigate."}},
            "required": ["description"],
            "additionalProperties": False,
        },
        read_only=True,
        requires_approval=False,
        group="agent",
    )

    def __init__(self, config) -> None:
        self._config = config
        self._llm_client = None
        self._tools = None
        self._settings = None

    def _ensure_ready(self) -> None:
        if self._llm_client is not None:
            return
        # Lazy + function-local imports avoid an agent<->tools import cycle.
        from allCode.llm.factory import create_llm_client
        from allCode.llm.settings import ModelSettings
        from allCode.tools.builtin import builtin_tools
        from allCode.tools.registry import ToolRegistry

        self._llm_client = create_llm_client(self._config)
        self._settings = ModelSettings.from_config(self._config)
        inspection = [tool for tool in builtin_tools() if tool.definition.name in _INSPECTION_TOOLS]
        self._tools = ToolRegistry(inspection)

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        description = str((call.arguments or {}).get("description", "")).strip()
        if not description:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error="description is required", error_type="missing_description")
        try:
            self._ensure_ready()
            from allCode.agent.loop import AgentLoop
            from allCode.agent.model_router import ModelRouter
            from allCode.core.event_bus import AsyncEventBus
            from allCode.core.models import TurnInput
            from allCode.tools.approval import ApprovalManager

            bus = AsyncEventBus()
            loop = AgentLoop(
                llm_client=self._llm_client,
                settings=self._settings,
                tools=self._tools,
                event_bus=bus,
                approval=ApprovalManager(mode="auto"),
                model_router=ModelRouter(llm_client=self._llm_client, settings=self._settings),
            )
            sub_prompt = f"코드 수정 없이 분석만 수행하세요. 다음을 조사해 결과를 정리해줘:\n{description}"
            result = await loop.run_turn(TurnInput(user_prompt=sub_prompt, workspace=context.workspace))
            await bus.close()
        except Exception as exc:  # noqa: BLE001 - surface any sub-agent failure as a tool error
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)
        answer = result.final_answer or ""
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=result.status in {"success", "partial"},
            content=answer,
            error=None if result.status in {"success", "partial"} else f"sub-agent status: {result.status}",
            metadata={"subagent_status": result.status},
        )


class DelegateTaskTool:
    """Delegate a self-contained, WRITABLE task to a sub-agent.

    Unlike ``task`` (read-only), this sub-agent gets the full toolset and may
    edit files and run commands to complete a scoped change, then reports back
    what it changed. Approval-gated so delegation of write authority is explicit;
    the sub-agent itself runs in auto mode within that approved scope.
    """

    definition = ToolDefinition(
        name="delegate_task",
        description=(
            "Delegate a self-contained change to a sub-agent that CAN edit files and run commands. "
            "Use for a scoped implementation/refactor that can proceed independently. Returns the "
            "sub-agent's summary plus the list of files it created/modified/deleted."
        ),
        parameters={
            "type": "object",
            "properties": {"description": {"type": "string", "description": "The task for the sub-agent to carry out."}},
            "required": ["description"],
            "additionalProperties": False,
        },
        read_only=False,
        requires_approval=True,
        group="agent",
        risk="high",
    )

    def __init__(self, config) -> None:
        self._config = config
        self._llm_client = None
        self._tools = None
        self._settings = None
        self._implementation_settings = None

    def _ensure_ready(self) -> None:
        if self._llm_client is not None:
            return
        from allCode.llm.factory import create_llm_client
        from allCode.llm.settings import ModelSettings
        from allCode.tools.builtin import builtin_tools
        from allCode.tools.registry import ToolRegistry

        self._llm_client = create_llm_client(self._config)
        self._settings = ModelSettings.from_config(self._config)
        self._implementation_settings = ModelSettings.implementation_from_config(self._config)
        # Full toolset (excluding nested delegation, to keep depth-1).
        tools = [tool for tool in builtin_tools() if tool.definition.name not in {"task", "delegate_task"}]
        self._tools = ToolRegistry(tools)

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        description = str((call.arguments or {}).get("description", "")).strip()
        if not description:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error="description is required", error_type="missing_description")
        if not context.workspace.writable:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error="workspace is not writable", error_type="read_only_workspace")
        try:
            self._ensure_ready()
            from allCode.agent.loop import AgentLoop
            from allCode.agent.model_router import ModelRouter
            from allCode.core.event_bus import AsyncEventBus
            from allCode.core.models import TurnInput
            from allCode.tools.approval import ApprovalManager

            bus = AsyncEventBus()
            loop = AgentLoop(
                llm_client=self._llm_client,
                settings=self._settings,
                implementation_settings=self._implementation_settings,
                tools=self._tools,
                event_bus=bus,
                approval=ApprovalManager(mode="auto"),
                model_router=ModelRouter(llm_client=self._llm_client, settings=self._settings),
            )
            result = await loop.run_turn(TurnInput(user_prompt=description, workspace=context.workspace))
            await bus.close()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)
        ok = result.status in {"success", "partial"}
        changed = list(result.modified_files)
        created = list(result.created_files)
        deleted = list(result.deleted_files)
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=ok,
            content=result.final_answer or "",
            error=None if ok else f"sub-agent status: {result.status}",
            metadata={
                "subagent_status": result.status,
                "created_files": created,
                "changed_files": changed,
                "deleted_files": deleted,
            },
        )

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

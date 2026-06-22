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
        tools = [tool for tool in builtin_tools() if tool.definition.name not in {"task", "delegate_task", "parallel_tasks"}]
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


class ParallelTasksTool:
    """Run several INDEPENDENT implementation sub-tasks in parallel, each isolated
    in its own git worktree, then auto-merge the branches back.

    Each parallel sub-agent uses ONLY the models named in config (model_name for
    reasoning, implementation_model_name for code) — never an arbitrary model.
    Non-overlapping edits merge automatically; genuine conflicts are handed to a
    config-model resolver sub-agent, and any still unresolved are isolated and
    reported (their branches preserved) rather than silently mangled. The user's
    current branch/working tree is untouched; results land on an integration
    branch the user adopts explicitly.
    """

    definition = ToolDefinition(
        name="parallel_tasks",
        description=(
            "Run multiple INDEPENDENT implementation sub-tasks concurrently, each in its own "
            "isolated git worktree, then merge the results back automatically (conflicts are "
            "reported). Use ONLY for sub-tasks that do not depend on each other's output. Returns "
            "a per-task board plus the integration branch to adopt. Requires a git repository."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Independent sub-task descriptions to run in parallel (2-6).",
                }
            },
            "required": ["tasks"],
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
        self._settings = None
        self._implementation_settings = None

    def _ensure_ready(self) -> None:
        if self._llm_client is not None:
            return
        from allCode.llm.factory import create_llm_client
        from allCode.llm.settings import ModelSettings

        self._llm_client = create_llm_client(self._config)
        # Model constraint: parallel sub-agents use ONLY the config-named models.
        self._settings = ModelSettings.from_config(self._config)
        self._implementation_settings = ModelSettings.implementation_from_config(self._config)

    def _build_tools(self):
        from allCode.tools.builtin import builtin_tools
        from allCode.tools.registry import ToolRegistry

        excluded = {"task", "delegate_task", "parallel_tasks"}
        sandbox = getattr(self._config.workspace, "shell_sandbox", "off")
        tools = [t for t in builtin_tools(shell_sandbox=sandbox) if t.definition.name not in excluded]
        return ToolRegistry(tools)

    async def _run_subagent(self, prompt: str, worktree):
        from allCode.agent.loop import AgentLoop
        from allCode.agent.model_router import ModelRouter
        from allCode.core.event_bus import AsyncEventBus
        from allCode.core.models import TurnInput, WorkspaceRef
        from allCode.tools.approval import ApprovalManager

        bus = AsyncEventBus()
        loop = AgentLoop(
            llm_client=self._llm_client,
            settings=self._settings,
            implementation_settings=self._implementation_settings,
            tools=self._build_tools(),
            event_bus=bus,
            approval=ApprovalManager(mode="auto"),
            model_router=ModelRouter(llm_client=self._llm_client, settings=self._settings),
        )
        try:
            return await loop.run_turn(
                TurnInput(user_prompt=prompt, workspace=WorkspaceRef(root=str(worktree), writable=True))
            )
        finally:
            await bus.close()

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        raw = (call.arguments or {}).get("tasks")
        descriptions = [str(t).strip() for t in raw if str(t).strip()] if isinstance(raw, list) else []
        if len(descriptions) < 2:
            return ToolResult(
                call_id=call.id, name=call.name, ok=False,
                error="tasks must list at least two independent sub-tasks", error_type="invalid_tasks",
            )
        if not context.workspace.writable:
            return ToolResult(
                call_id=call.id, name=call.name, ok=False,
                error="workspace is not writable", error_type="read_only_workspace",
            )
        try:
            self._ensure_ready()
            from allCode.agent.parallel_orchestrator import ParallelTaskSpec, RunnerResult, run_parallel_tasks

            async def runner(spec: ParallelTaskSpec, worktree) -> RunnerResult:
                result = await self._run_subagent(spec.description, worktree)
                return RunnerResult(ok=result.status in {"success", "partial"}, summary=result.final_answer or "")

            async def resolver(integ_worktree, conflicted: list[str]) -> bool:
                prompt = (
                    "다음 파일에 git 병합 충돌 마커(<<<<<<<, =======, >>>>>>>)가 있습니다: "
                    f"{', '.join(conflicted)}. 양쪽 변경 의도를 모두 보존하도록 신중히 충돌을 해소하고 "
                    "모든 충돌 마커를 제거하세요. 충돌 해소 외의 변경은 하지 마세요."
                )
                result = await self._run_subagent(prompt, integ_worktree)
                return result.status in {"success", "partial"}

            specs = [ParallelTaskSpec(id=str(i), description=d) for i, d in enumerate(descriptions)]
            report = await run_parallel_tasks(
                specs,
                workspace_root=context.workspace.root,
                runner=runner,
                conflict_resolver=resolver,
                max_concurrency=min(4, len(specs)),
            )
        except ValueError as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type="parallel_unavailable")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(call_id=call.id, name=call.name, ok=False, error=str(exc), error_type=exc.__class__.__name__)
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=bool(report.applied) and not report.conflicts,
            content=report.board(),
            metadata={
                "integration_branch": report.integration_branch,
                "merged_files": report.merged_files,
                "applied": [o.id for o in report.applied],
                "conflicts": [o.id for o in report.conflicts],
            },
        )

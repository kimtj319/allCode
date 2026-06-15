"""Runtime assembly for CLI and TUI execution paths."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from allCode.agent.context import ContextBuilder
from allCode.agent.context_factory import build_runtime_context_builder
from allCode.agent.loop import AgentLoop
from allCode.agent.model_router import ModelRouter
from allCode.config.schema import AppConfig
from allCode.core.event_bus import AsyncEventBus
from allCode.core.events import AgentEvent
from allCode.core.models import TurnInput, WorkspaceRef
from allCode.core.result import TurnResult
from allCode.llm.client import LLMClient
from allCode.llm.factory import create_llm_client
from allCode.llm.settings import ModelSettings
from allCode.memory.session_summary import SessionSummary
from allCode.memory.session_state_store import SessionStateStore
from allCode.telemetry import AgentSessionLogger
from allCode.tools.builtin import builtin_tools
from allCode.tools.approval import ApprovalHandler, ApprovalManager
from allCode.tools.hooks import HookRunner
from allCode.tools.mcp import load_mcp_tools
from allCode.tools.registry import ToolRegistry
from allCode.tools.web_provider import fetch_provider_from_config, provider_from_config
from allCode.workspace.git_ops import commit_all as git_commit_all
from allCode.workspace.git_ops import is_git_repo

EventHandler = Callable[[AgentEvent], Awaitable[None]]
TurnRunner = Callable[[str, EventHandler, ApprovalHandler | None], Awaitable[None]]


async def run_agent_turn(
    prompt: str,
    *,
    config: AppConfig,
    llm_client: LLMClient | None = None,
    tools: ToolRegistry | None = None,
    context_builder: ContextBuilder | None = None,
    event_handler: EventHandler | None = None,
    approval_handler: ApprovalHandler | None = None,
    session_logger: AgentSessionLogger | None = None,
) -> TurnResult:
    """Run a single agent turn with optional event forwarding."""

    event_bus = AsyncEventBus()
    logger = session_logger or AgentSessionLogger.create(config=config)
    event_bus.subscribe(None, logger.handle_event)
    if event_handler is not None:
        event_bus.subscribe(None, event_handler)
    use_model_router = llm_client is None
    effective_llm = llm_client or create_llm_client(config)
    settings = ModelSettings.from_config(config)
    effective_context_builder = context_builder or build_runtime_context_builder(config)
    await _load_persisted_session_state(config, logger.session_id, effective_context_builder)
    loop = AgentLoop(
        llm_client=effective_llm,
        settings=settings,
        tools=tools or runtime_tool_registry(config),
        event_bus=event_bus,
        approval=ApprovalManager(mode=config.approval.mode, session_allow=config.approval.session_allow),
        approval_handler=approval_handler,
        context_builder=effective_context_builder,
        model_router=ModelRouter(llm_client=effective_llm, settings=settings) if use_model_router else None,
        hook_runner=HookRunner(config.hooks),
    )
    turn_input = TurnInput(
        user_prompt=prompt,
        workspace=WorkspaceRef(root=config.workspace.root, writable=config.workspace.sandbox_enabled),
        session_id=logger.session_id,
    )
    event_bus_closed = False
    try:
        await logger.log(
            category="turn",
            event_type="user_request_received",
            message="User request received.",
            payload={
                "prompt": prompt,
                "workspace": config.workspace.root,
                "model": config.model.model_name,
                "base_url": config.model.base_url,
                "approval_mode": config.approval.mode,
            },
        )
        result = await loop.run_turn(turn_input)
        await _save_persisted_session_state(config, turn_input.session_id, effective_context_builder)
        _maybe_auto_commit(config, result, prompt)
        _remember_result_targets(effective_context_builder, result)
        effective_context_builder.remember_user_prompt(turn_input.session_id, prompt)
        effective_context_builder.remember_user_note(turn_input.session_id, prompt)
        effective_context_builder.remember_assistant_summary(turn_input.session_id, result.final_answer)
        await _persist_user_note_summary(config, turn_input.session_id, effective_context_builder.extract_user_note(prompt))
        await event_bus.close()
        event_bus_closed = True
        await logger.log(
            category="turn",
            event_type="runtime_turn_result",
            turn_id=result.turn_id,
            message=f"Runtime turn result: {result.status}.",
            payload=result.model_dump(mode="json"),
        )
        return result
    finally:
        if not event_bus_closed:
            await event_bus.close()


def make_tui_turn_runner(
    *,
    config: AppConfig,
    llm_client: LLMClient | None = None,
    tools: ToolRegistry | None = None,
    context_builder: ContextBuilder | None = None,
    session_logger: AgentSessionLogger | None = None,
) -> TurnRunner:
    """Build a Textual-compatible turn runner without coupling TUI to agent internals."""

    context_builder = context_builder or build_runtime_context_builder(config)
    session_logger = session_logger or AgentSessionLogger.create(config=config)

    async def run(prompt: str, event_handler: EventHandler, approval_handler: ApprovalHandler | None = None) -> None:
        await run_agent_turn(
            prompt,
            config=config,
            llm_client=llm_client,
            tools=tools,
            context_builder=context_builder,
            event_handler=event_handler,
            approval_handler=approval_handler,
            session_logger=session_logger,
        )

    return run


def runtime_tool_registry(config: AppConfig) -> ToolRegistry:
    registry = ToolRegistry(
        builtin_tools(
            web_search_provider=provider_from_config(config.web),
            web_fetch_provider=fetch_provider_from_config(config.web),
            shell_sandbox=config.workspace.shell_sandbox,
        )
    )
    from allCode.tools.builtin.task import TaskTool

    try:
        registry.register(TaskTool(config))
    except ValueError:
        pass
    mcp_tools, _manager = load_mcp_tools(config)
    for tool in mcp_tools:
        try:
            registry.register(tool)
        except ValueError:
            # Name collision with a builtin or another MCP tool; skip the duplicate.
            continue
    return registry


async def _persist_user_note_summary(config: AppConfig, session_id: str, note: str | None) -> None:
    if note is None:
        return
    summary_store = SessionSummary(Path(config.workspace.root))
    existing = await summary_store.load(session_id)
    if note in existing:
        return
    updated = f"{existing.rstrip()}\n- {note}\n".lstrip()
    await summary_store.save(session_id, updated)


async def _load_persisted_session_state(config: AppConfig, session_id: str, context_builder: ContextBuilder) -> None:
    store = SessionStateStore(Path(config.workspace.root))
    snapshot = await store.load_snapshot(session_id, workspace_root=config.workspace.root)
    if snapshot is not None:
        context_builder.session_state.load_snapshot(snapshot)


async def _save_persisted_session_state(config: AppConfig, session_id: str, context_builder: ContextBuilder) -> None:
    store = SessionStateStore(Path(config.workspace.root))
    snapshot = context_builder.session_state.to_snapshot(session_id=session_id, workspace_root=config.workspace.root)
    await store.save_snapshot(snapshot)


def _maybe_auto_commit(config: AppConfig, result: TurnResult, prompt: str) -> None:
    if not config.git.auto_commit:
        return
    if result.status not in {"success", "partial"}:
        return
    if not (result.created_files or result.completion_evidence.has_file_change()):
        return
    root = config.workspace.root
    if not is_git_repo(root):
        return
    subject = " ".join(prompt.split())[:72] or "allCode change"
    git_commit_all(root, f"allCode: {subject}")


def _remember_result_targets(context_builder: ContextBuilder, result: TurnResult) -> None:
    manifest = result.completion_evidence.project_manifest
    if manifest is not None:
        context_builder.remember_project_manifest(manifest, turn_id=result.turn_id)
    document_manifest = result.completion_evidence.document_manifest
    if document_manifest is not None:
        context_builder.remember_document_manifest(document_manifest, turn_id=result.turn_id)
    for path in result.created_files:
        context_builder.remember_target(path, turn_id=result.turn_id, summary="created file")
    for path in result.modified_files:
        context_builder.remember_target(path, turn_id=result.turn_id, summary="modified file")
    for path in result.deleted_files:
        context_builder.remember_target(path, turn_id=result.turn_id, summary="deleted file")

"""Runtime assembly for CLI and TUI execution paths."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from allCode.agent.context import ContextBuilder
from allCode.agent.context_factory import build_runtime_context_builder
from allCode.agent.loop import AgentLoop
from allCode.config.schema import AppConfig
from allCode.core.event_bus import AsyncEventBus
from allCode.core.events import AgentEvent
from allCode.core.models import TurnInput, WorkspaceRef
from allCode.core.result import TurnResult
from allCode.llm.client import LLMClient
from allCode.llm.factory import create_llm_client
from allCode.llm.settings import ModelSettings
from allCode.tools.builtin import builtin_tools
from allCode.tools.approval import ApprovalManager
from allCode.tools.registry import ToolRegistry
from allCode.tools.web_provider import provider_from_config

EventHandler = Callable[[AgentEvent], Awaitable[None]]
TurnRunner = Callable[[str, EventHandler], Awaitable[None]]


async def run_agent_turn(
    prompt: str,
    *,
    config: AppConfig,
    llm_client: LLMClient | None = None,
    tools: ToolRegistry | None = None,
    context_builder: ContextBuilder | None = None,
    event_handler: EventHandler | None = None,
) -> TurnResult:
    """Run a single agent turn with optional event forwarding."""

    event_bus = AsyncEventBus()
    if event_handler is not None:
        event_bus.subscribe(None, event_handler)
    loop = AgentLoop(
        llm_client=llm_client or create_llm_client(config),
        settings=ModelSettings.from_config(config),
        tools=tools or runtime_tool_registry(config),
        event_bus=event_bus,
        approval=ApprovalManager(mode=config.approval.mode, session_allow=config.approval.session_allow),
        context_builder=context_builder or build_runtime_context_builder(config),
    )
    turn_input = TurnInput(
        user_prompt=prompt,
        workspace=WorkspaceRef(root=config.workspace.root, writable=config.workspace.sandbox_enabled),
    )
    try:
        return await loop.run_turn(turn_input)
    finally:
        await event_bus.close()


def make_tui_turn_runner(
    *,
    config: AppConfig,
    llm_client: LLMClient | None = None,
    tools: ToolRegistry | None = None,
) -> TurnRunner:
    """Build a Textual-compatible turn runner without coupling TUI to agent internals."""

    context_builder = build_runtime_context_builder(config)

    async def run(prompt: str, event_handler: EventHandler) -> None:
        await run_agent_turn(
            prompt,
            config=config,
            llm_client=llm_client,
            tools=tools,
            context_builder=context_builder,
            event_handler=event_handler,
        )

    return run


def runtime_tool_registry(config: AppConfig) -> ToolRegistry:
    return ToolRegistry(
        builtin_tools(
            web_search_provider=provider_from_config(config.web),
        )
    )

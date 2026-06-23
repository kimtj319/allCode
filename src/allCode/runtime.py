"""Runtime assembly for CLI and TUI execution paths."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from allCode.agent.context import ContextBuilder
from allCode.agent.context_factory import build_runtime_context_builder
from allCode.agent.loop import AgentLoop
from allCode.agent.model_router import ModelRouter
from allCode.agent.steering import SteeringQueue
from allCode.config.schema import AppConfig
from allCode.core.event_bus import AsyncEventBus
from allCode.core.events import AgentEvent, TurnFinalized
from allCode.core.models import TurnInput, WorkspaceRef
from allCode.core.result import TurnResult
from allCode.llm.client import LLMClient
from allCode.llm.factory import create_llm_client
from allCode.llm.settings import ModelSettings
from allCode.llm.usage_tracking import UsageRecordingLLMClient
from allCode.memory.usage_store import UsageStore
from allCode.memory.session_summary import SessionSummary
from allCode.memory.session_state_store import SessionStateStore
from allCode.memory.conversation_store import ConversationStore
from allCode.workspace.checkpoint_store import CheckpointStore
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


def _plan_mode_prompt(prompt: str) -> str:
    """Wrap a request for plan mode: read-only investigation that yields a plan.

    The wording includes read-only and no-shell terms the constraint extractor
    recognizes, so routing deterministically strips mutation/shell tools — the
    same hard read-only Claude Code's plan mode enforces — regardless of what the
    underlying request asks for."""
    return (
        "[계획 모드 / PLAN MODE — read-only, do not edit]\n"
        "지금은 계획 모드입니다. 파일 수정 금지, 명령 실행 금지(읽기 전용).\n"
        "관련 파일을 필요한 만큼만 간단히 확인한 뒤, 더 이상 탐색하지 말고 **실행 계획을 최종 "
        "답변으로 즉시 작성**하세요. 저장소 구조 요약이 아니라 아래 형식의 '실행 계획'을 작성합니다. "
        "더 조사할 것이 없으면 바로 계획을 쓰세요(라운드를 소진하지 마세요).\n\n"
        "## 실행 계획\n"
        "1. 단계별 작업(무엇을·왜·어떻게)\n"
        "2. 영향 받는 파일/심볼\n"
        "3. 검증(테스트) 방법\n"
        "4. 위험과 대안\n\n"
        "실제 구현은 사용자가 `/plan off`로 계획 모드를 끈 뒤 진행합니다.\n\n"
        f"사용자 요청:\n{prompt}"
    )


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
    steering=None,
    images: list[str] | None = None,
) -> TurnResult:
    """Run a single agent turn with optional event forwarding."""

    event_bus = AsyncEventBus()
    logger = session_logger or AgentSessionLogger.create(config=config)
    event_bus.subscribe(None, logger.handle_event)
    if event_handler is not None:
        event_bus.subscribe(None, event_handler)
    use_model_router = llm_client is None
    effective_llm = llm_client or create_llm_client(config)
    # Attribute every non-streaming model call (router, planner, file editor) to
    # its model so /status can break down usage per model. Streaming round usage
    # is recorded separately via the ModelMetricsRecorded event.
    effective_llm = UsageRecordingLLMClient(effective_llm, UsageStore(config.workspace.root), event_bus=event_bus)
    settings = ModelSettings.from_config(config)
    implementation_settings = ModelSettings.implementation_from_config(config)
    effective_context_builder = context_builder or build_runtime_context_builder(config)
    await _load_persisted_session_state(config, logger.session_id, effective_context_builder)
    checkpoint_store = CheckpointStore(config.workspace.root)
    checkpoint_store.begin_turn()
    workspace_root_path = Path(config.workspace.root).expanduser().resolve()

    def _checkpoint(target: str) -> None:
        if not target:
            return
        path = Path(target)
        if not path.is_absolute():
            path = workspace_root_path / path
        checkpoint_store.snapshot(path)

    plan_approval = _build_plan_approval(config, approval_handler)
    hook_runner = HookRunner(config.hooks)
    # Plan mode (Claude Code-style): force the whole turn read-only and produce a
    # plan. Cap inspection so the loop investigates briefly and then finalizes the
    # plan instead of probing read-only until max_rounds (which would fall back to
    # a structure summary rather than a plan).
    plan_mode = bool(getattr(config.agent, "plan_mode", False))
    loop = AgentLoop(
        llm_client=effective_llm,
        settings=settings,
        implementation_settings=implementation_settings,
        tools=tools or runtime_tool_registry(config),
        event_bus=event_bus,
        approval=ApprovalManager(
            mode=config.approval.mode,
            session_allow=config.approval.session_allow,
            allow_rules=config.approval.allow,
            deny_rules=config.approval.deny,
        ),
        approval_handler=approval_handler,
        context_builder=effective_context_builder,
        model_router=ModelRouter(llm_client=effective_llm, settings=settings) if use_model_router else None,
        show_reasoning=config.ui.show_thinking,
        unified_loop=config.agent.unified_loop,
        max_rounds=config.agent.max_rounds,
        inspect_action_budget=min(config.agent.inspect_action_budget, 6) if plan_mode else config.agent.inspect_action_budget,
        inspect_round_budget=min(config.agent.inspect_round_budget, 3) if plan_mode else config.agent.inspect_round_budget,
        system_prompt_append=config.agent.system_prompt_append,
        hook_runner=hook_runner,
        checkpoint=_checkpoint,
        plan_approval=plan_approval,
        steering=steering,
    )
    # Plan mode: read-only directive (the extractor recognizes its read-only/
    # no-shell terms, so routing hard-strips mutation/shell tools) and a
    # non-writable workspace as a second line of defense.
    effective_prompt = _plan_mode_prompt(prompt) if plan_mode else prompt
    turn_input = TurnInput(
        user_prompt=effective_prompt,
        workspace=WorkspaceRef(
            root=config.workspace.root,
            writable=config.workspace.sandbox_enabled and not plan_mode,
        ),
        session_id=logger.session_id,
        images=list(images or []),
        plan_mode=plan_mode,
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
        # session_start hooks: run once per process, inject stdout into every turn.
        if hook_runner.active and not effective_context_builder.session_start_done(logger.session_id):
            session_ctx = await hook_runner.session_start(
                session_id=logger.session_id, workspace=config.workspace.root
            )
            effective_context_builder.set_session_start_context(logger.session_id, session_ctx)
        context_blocks: list[str] = []
        session_ctx = effective_context_builder.session_start_context(logger.session_id)
        if session_ctx:
            context_blocks.append(f"[session context]\n{session_ctx}")
        # user_prompt_submit hooks: may block the turn or inject extra context.
        if hook_runner.active:
            outcome = await hook_runner.user_prompt_submit(prompt)
            if outcome.blocked:
                blocked = _hook_blocked_result(reason=outcome.reason)
                if event_handler is not None:
                    await event_handler(
                        TurnFinalized(
                            turn_id=blocked.turn_id,
                            message="Turn blocked by user_prompt_submit hook.",
                            status=blocked.status,
                            final_answer=blocked.final_answer,
                        )
                    )
                await event_bus.close()
                event_bus_closed = True
                return blocked
            if outcome.injected_context:
                context_blocks.append(f"[hook context]\n{outcome.injected_context}")
        if context_blocks:
            turn_input = turn_input.model_copy(
                update={"user_prompt": prompt + "\n\n" + "\n\n".join(context_blocks)}
            )
        result = await loop.run_turn(turn_input)
        # stop hooks observe the finished turn (e.g. format/lint) before auto-commit
        # so any changes they make are captured.
        if hook_runner.active:
            await hook_runner.stop(status=result.status, final_answer=result.final_answer)
        await _save_persisted_session_state(config, turn_input.session_id, effective_context_builder)
        _maybe_auto_commit(config, result, prompt)
        _remember_result_targets(effective_context_builder, result)
        effective_context_builder.remember_user_prompt(turn_input.session_id, prompt)
        effective_context_builder.remember_user_note(turn_input.session_id, prompt)
        effective_context_builder.remember_assistant_summary(turn_input.session_id, result.final_answer)
        await _persist_user_note_summary(config, turn_input.session_id, effective_context_builder.extract_user_note(prompt))
        _append_conversation_exchange(config, turn_input.session_id, prompt, result.final_answer)
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
    steering = SteeringQueue()

    async def run(
        prompt: str,
        event_handler: EventHandler,
        approval_handler: ApprovalHandler | None = None,
        *,
        images: list[str] | None = None,
    ) -> None:
        # Drop any stale steering left over from a previous turn.
        steering.drain()
        await run_agent_turn(
            prompt,
            config=config,
            llm_client=llm_client,
            tools=tools,
            context_builder=context_builder,
            event_handler=event_handler,
            approval_handler=approval_handler,
            session_logger=session_logger,
            steering=steering,
            images=images,
        )

    # The TUI pushes mid-turn user input here; the running turn drains it at
    # each round boundary.
    run.steering = steering  # type: ignore[attr-defined]
    return run


def _build_plan_approval(config: AppConfig, approval_handler: ApprovalHandler | None):
    """Build a plan-mode gate from the interactive approval handler.

    Returns None unless plan mode is on and an approval handler exists (e.g. a
    headless run has no handler, so plan mode cannot block — it proceeds). The
    plan is presented as an approval request named ``plan``; approve → proceed,
    deny → abort before any file is written."""
    if not config.approval.plan_mode or approval_handler is None:
        return None

    from allCode.core.models import ToolCall
    from allCode.tools.approval import ApprovalDecision, ApprovalRequest

    async def plan_approval(summary: str) -> bool:
        request = ApprovalRequest(
            tool_name="plan",
            decision=ApprovalDecision(allowed=False, requires_approval=True, preview=summary, risk="medium"),
            preview=summary,
            risk="medium",
            call=ToolCall(id="plan-approval", name="plan", arguments={}),
        )
        action = await approval_handler(request)
        return action in {"approve_once", "allow_session"}

    return plan_approval


def runtime_tool_registry(config: AppConfig) -> ToolRegistry:
    registry = ToolRegistry(
        builtin_tools(
            web_search_provider=provider_from_config(config.web),
            web_fetch_provider=fetch_provider_from_config(config.web),
            shell_sandbox=config.workspace.shell_sandbox,
        )
    )
    from allCode.tools.builtin.task import DelegateTaskTool, ParallelTasksTool, TaskTool

    for delegated in (TaskTool(config), DelegateTaskTool(config), ParallelTasksTool(config)):
        try:
            registry.register(delegated)
        except ValueError:
            pass
    # Expose the `skill` tool only when the project defines skills, so the model
    # sees available skills (in its description) and can load them on demand.
    from allCode.tools.builtin.skill import SkillTool

    skill_tool = SkillTool(config)
    if skill_tool.has_skills:
        try:
            registry.register(skill_tool)
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


def _append_conversation_exchange(config: AppConfig, session_id: str, prompt: str, answer: str) -> None:
    try:
        ConversationStore(config.workspace.root).append_exchange(session_id, prompt=prompt, answer=answer)
    except OSError:
        pass


def seed_resumed_session(config: AppConfig, context_builder: ContextBuilder, session_id: str) -> int:
    """Replay a previous session's conversation into the context builder so a
    resumed session continues with the prior back-and-forth. Returns the number
    of exchanges restored. The reused session_id also restores the state snapshot
    on the first turn (it is keyed by session_id)."""

    exchanges = ConversationStore(config.workspace.root).load(session_id)
    restored = 0
    for role, text in exchanges:
        if role == "user":
            context_builder.remember_user_prompt(session_id, text)
            context_builder.remember_user_note(session_id, text)
            restored += 1
        elif role == "assistant":
            context_builder.remember_assistant_summary(session_id, text)
    return restored


def _hook_blocked_result(*, reason: str) -> TurnResult:
    from uuid import uuid4

    message = f"요청이 user_prompt_submit 훅에 의해 차단되었습니다: {reason}".strip()
    return TurnResult(turn_id=uuid4().hex, status="cancelled", final_answer=message, error_message=reason)


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
    # Prefer a Conventional-Commit message derived from the actual diff; fall
    # back to the prompt subject when nothing classifiable changed.
    from allCode.workspace.git_ops import derive_commit_message

    message = derive_commit_message(root)
    if message == "chore: update workspace":
        subject = " ".join(prompt.split())[:72] or "allCode change"
        message = f"allCode: {subject}"
    git_commit_all(root, message)


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

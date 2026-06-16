"""Skeleton-first project generation workflow."""

from __future__ import annotations

from uuid import uuid4

from allCode.agent.api_obligation_checker import declared_public_api_symbols, planned_public_api_symbols
from allCode.agent.completion_checker import CompletionChecker
from allCode.agent.final_reporter import FinalReporter
from allCode.agent.language import detect_response_language
from allCode.agent.project_planner import ModelProjectPlanner
from allCode.agent.project_plan_quality import project_plan_quality_errors
from allCode.agent.router import RoutingDecision, RuleBasedRouter
from allCode.agent.task_plan import ProjectPlan
from allCode.agent.task_loop_digest import TaskLoopDigest, build_task_loop_digest
from allCode.agent.validation_runner import ValidationResult, ValidationRunner
from allCode.agent.workflow_actions import WorkflowActions, WorkflowStepRecord
from allCode.agent.workflow_completion import build_project_manifest
from allCode.agent.workflow_digest import workflow_digest
from allCode.agent.workflow_editor import ModelWorkflowEditor
from allCode.agent.workflow_repair import repair_completion_check, repair_until_valid
from allCode.agent.workflow_result import (
    GenerationWorkflowResult,
    build_failed_workflow_result,
    build_rejected_workflow_result,
    build_workflow_turn_result,
)
from allCode.agent.workflow_routing import workflow_target_root_from_routing
from allCode.core.event_bus import AsyncEventBus, EventBus
from allCode.core.events import (
    GenerationWorkflowFinished,
    GenerationWorkflowStarted,
)
from allCode.core.models import TurnInput
from allCode.core.result import CompletionEvidence, RecoveryState
from allCode.generation.strategy import GenerationRequest, StrategyRegistry
from allCode.generation.strategies import default_strategy_registry
from allCode.llm.client import LLMClient
from allCode.llm.settings import ModelSettings
from allCode.tools.approval import ApprovalManager
from allCode.tools.builtin import builtin_tools
from allCode.tools.executor import ToolExecutor
from allCode.tools.registry import ToolRegistry


class GenerationWorkflow:
    def __init__(
        self,
        *,
        strategy_registry: StrategyRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
        event_bus: EventBus | None = None,
        router: RuleBasedRouter | None = None,
        validation_runner: ValidationRunner | None = None,
        completion_checker: CompletionChecker | None = None,
        final_reporter: FinalReporter | None = None,
        llm_client: LLMClient | None = None,
        settings: ModelSettings | None = None,
        editor_settings: ModelSettings | None = None,
        model_planner: ModelProjectPlanner | None = None,
        max_repair_attempts: int = 5,
        plan_approval=None,
    ) -> None:
        # Optional async gate: called with the plan summary after the plan is
        # built but before any file is written. Returning False aborts the
        # generation (plan mode — present the plan, wait for approval).
        self._plan_approval = plan_approval
        self.strategy_registry = strategy_registry or default_strategy_registry()
        self.event_bus = event_bus or AsyncEventBus()
        self.router = router or RuleBasedRouter()
        self.validation_runner = validation_runner or ValidationRunner()
        self.completion_checker = completion_checker or CompletionChecker()
        self.final_reporter = final_reporter or FinalReporter()
        # Planner stays on the base/reasoning model; the editor (code generation,
        # editing, repair) uses the higher-performance implementation model when
        # one is configured. Falls back to base settings.
        editor_settings = editor_settings or settings
        self.model_planner = model_planner or (
            ModelProjectPlanner(llm_client=llm_client, settings=settings)
            if llm_client is not None and settings is not None
            else None
        )
        self.model_editor = (
            ModelWorkflowEditor(llm_client=llm_client, settings=editor_settings)
            if llm_client is not None and editor_settings is not None
            else None
        )
        self.max_repair_attempts = max_repair_attempts
        self.tool_executor = tool_executor or ToolExecutor(
            registry=ToolRegistry(builtin_tools()),
            approval=ApprovalManager(mode="auto"),
        )
        self.actions = WorkflowActions(tool_executor=self.tool_executor, event_bus=self.event_bus)

    async def run(self, turn_input: TurnInput, *, routing: RoutingDecision | None = None) -> GenerationWorkflowResult:
        turn_id = uuid4().hex
        routing = routing or self.router.classify(turn_input.user_prompt)
        routing = routing.model_copy(
            update={
                "tool_capabilities": set(routing.tool_capabilities) | {"mutate_file", "run_validation"},
                "requires_tools": True,
                "requires_mutation": True,
                "requires_validation": True,
            }
        )
        request = GenerationRequest(
            prompt=turn_input.user_prompt,
            workspace_root=turn_input.workspace.root,
            target_root=workflow_target_root_from_routing(turn_input.user_prompt, routing),
        )
        strategy = self.strategy_registry.select(request)
        completion_evidence = CompletionEvidence()
        recovery_states: list[RecoveryState] = []
        step_history: list[WorkflowStepRecord] = []
        task_loop_digests: list[TaskLoopDigest] = []
        validation_results: list[ValidationResult] = []
        repair_attempts = 0
        planning_digest = build_task_loop_digest(
            turn_input=turn_input,
            routing=routing,
            evidence=completion_evidence,
            current_step="planning",
            next_required_action="Create a skeleton-first plan that satisfies prompt-derived artifact obligations.",
        )
        task_loop_digests.append(planning_digest)
        plan = await self._create_plan(request, routing=routing, strategy=strategy, task_digest=planning_digest)

        await self._publish(
            GenerationWorkflowStarted(
                turn_id=turn_id,
                message="Generation workflow started.",
                data={
                    "target_root": plan.target_root,
                    "language": plan.language,
                    # Surface the plan so the UI can show the implementation plan and
                    # file tree before any code is written (Codex-style plan preview).
                    "files": [
                        {"path": file.path, "purpose": file.purpose, "stage": file.stage}
                        for file in plan.files
                    ],
                },
            )
        )

        if self._plan_approval is not None:
            approved = await self._plan_approval(_plan_summary(plan))
            if not approved:
                return build_rejected_workflow_result(
                    turn_id=turn_id,
                    plan=plan,
                    completion_evidence=completion_evidence,
                    task_loop_digests=task_loop_digests,
                )

        try:
            skeleton_digest = workflow_digest(
                turn_input,
                routing,
                completion_evidence,
                plan=plan,
                current_step="skeleton",
                next_required_action="Write skeleton files through file mutation tools.",
            )
            task_loop_digests.append(skeleton_digest)
            await self.actions.write_step_files("skeleton", plan, turn_input, turn_id, routing, completion_evidence, step_history)
            implementation_digest = workflow_digest(
                turn_input,
                routing,
                completion_evidence,
                plan=plan,
                current_step="implementation",
                next_required_action="Write implementation files and preserve requested behavior.",
            )
            task_loop_digests.append(implementation_digest)
            for file in plan.files_for_step("implementation"):
                if self.model_editor is not None:
                    file.content = await self.model_editor.generate_file(
                        file,
                        plan,
                        turn_input,
                        task_digest=implementation_digest.render(),
                    )
            await self.actions.write_step_files("implementation", plan, turn_input, turn_id, routing, completion_evidence, step_history)
            tests_digest = workflow_digest(
                turn_input,
                routing,
                completion_evidence,
                plan=plan,
                current_step="tests",
                next_required_action="Write requested test artifacts before validation.",
            )
            task_loop_digests.append(tests_digest)
            for file in plan.files_for_step("tests"):
                if self.model_editor is not None:
                    file.content = await self.model_editor.generate_file(
                        file,
                        plan,
                        turn_input,
                        task_digest=tests_digest.render(),
                    )
            await self.actions.write_step_files("tests", plan, turn_input, turn_id, routing, completion_evidence, step_history)

            validation_digest = workflow_digest(
                turn_input,
                routing,
                completion_evidence,
                plan=plan,
                current_step="validation",
                next_required_action="Run validation and capture the result.",
            )
            task_loop_digests.append(validation_digest)
            validation_results.extend(
                await self._run_validation_step(plan, turn_input, turn_id, routing, completion_evidence, step_history)
            )

            if validation_results and validation_results[-1].ok:
                await self.actions.record_skipped_step("repair", turn_id, step_history, "Validation passed before repair.")
            else:
                task_loop_digests.append(
                    workflow_digest(
                        turn_input,
                        routing,
                        completion_evidence,
                        recovery_states=recovery_states,
                        plan=plan,
                        current_step="repair",
                        next_required_action="Repair validation or completion failures, then validate again.",
                    )
                )
                repair_attempts = await repair_until_valid(
                    strategy=strategy,
                    plan=plan,
                    turn_input=turn_input,
                    turn_id=turn_id,
                    routing=routing,
                    completion_evidence=completion_evidence,
                    validation_results=validation_results,
                    recovery_states=recovery_states,
                    step_history=step_history,
                    actions=self.actions,
                    run_validation_step=self._run_validation_step,
                    repair_files=self._repair_files_from_model_or_strategy,
                    max_repair_attempts=self.max_repair_attempts,
                    completion_checker=self.completion_checker,
                )

            preliminary_check = self.completion_checker.check(
                workspace_root=turn_input.workspace.root,
                plan=plan,
                completion_evidence=completion_evidence,
                validation_results=validation_results,
            )
            repair_attempts += await repair_completion_check(
                strategy=strategy,
                check=preliminary_check,
                plan=plan,
                turn_input=turn_input,
                turn_id=turn_id,
                routing=routing,
                completion_evidence=completion_evidence,
                validation_results=validation_results,
                recovery_states=recovery_states,
                step_history=step_history,
                actions=self.actions,
                completion_checker=self.completion_checker,
                run_validation_step=self._run_validation_step,
                repair_files=self._repair_files_from_model_or_strategy,
                max_repair_attempts=self.max_repair_attempts,
                current_attempts=repair_attempts,
            )
            preliminary_check = self.completion_checker.check(
                workspace_root=turn_input.workspace.root,
                plan=plan,
                completion_evidence=completion_evidence,
                validation_results=validation_results,
            )
            completion_evidence.project_manifest = build_project_manifest(
                plan=plan,
                completion_evidence=completion_evidence,
            )
            final_report = ""
            final_check = preliminary_check
            if preliminary_check.ok:
                await self.actions.start_step("final_report", turn_id, step_history, "Rendering final report.")
                final_report = self.final_reporter.build(
                    plan=plan,
                    completion_evidence=completion_evidence,
                    validation_results=validation_results,
                    recovery_states=recovery_states,
                    repair_attempts=repair_attempts,
                    response_language=detect_response_language(turn_input.user_prompt),
                )
                final_check = self.completion_checker.check(
                    workspace_root=turn_input.workspace.root,
                    plan=plan,
                    completion_evidence=completion_evidence,
                    validation_results=validation_results,
                    final_report=final_report,
                )
                await self.actions.finish_step(
                    "final_report",
                    turn_id,
                    step_history,
                    "succeeded" if final_check.ok else "failed",
                    "Final report rendered.",
                )

            await self._publish(
                GenerationWorkflowFinished(
                    turn_id=turn_id,
                    message="Generation workflow finished.",
                    data={"status": "success" if final_check.ok else "failed", "errors": final_check.errors},
                )
            )
            return build_workflow_turn_result(
                turn_id=turn_id,
                plan=plan,
                completion_evidence=completion_evidence,
                validation_results=validation_results,
                final_check=final_check,
                final_report=final_report,
                step_history=step_history,
                task_loop_digests=task_loop_digests,
                repair_attempts=repair_attempts,
                recovery_states=recovery_states,
            )
        except Exception as exc:
            return build_failed_workflow_result(
                turn_id=turn_id,
                plan=plan,
                completion_evidence=completion_evidence,
                validation_results=validation_results,
                exc=exc,
                step_history=step_history,
                task_loop_digests=task_loop_digests,
                repair_attempts=repair_attempts,
                recovery_states=recovery_states,
            )

    async def _run_validation_step(
        self,
        plan: ProjectPlan,
        turn_input: TurnInput,
        turn_id: str,
        routing: RoutingDecision,
        completion_evidence: CompletionEvidence,
        step_history: list[WorkflowStepRecord],
    ) -> list[ValidationResult]:
        await self.actions.start_step("validation", turn_id, step_history, "Running validation commands.")
        results = await self.validation_runner.run_all(
            plan=plan,
            workspace=turn_input.workspace,
            session_id=turn_input.session_id,
            turn_id=turn_id,
            tool_executor=self.tool_executor,
            routing=routing,
            completion_evidence=completion_evidence,
            event_bus=self.event_bus,
        )
        status = "succeeded" if results and results[-1].ok else "failed"
        await self.actions.finish_step("validation", turn_id, step_history, status, "Validation completed.")
        return results

    async def _create_plan(
        self,
        request: GenerationRequest,
        *,
        routing: RoutingDecision,
        strategy,
        task_digest: TaskLoopDigest,
    ) -> ProjectPlan:
        target_hint = routing.target_hint or request.target_root
        if self.model_planner is not None:
            try:
                model_plan = await self.model_planner.create_plan(
                    request.prompt,
                    target_hint=target_hint,
                    task_digest=task_digest.render(),
                )
            except Exception:
                model_plan = None
            if model_plan is not None and _model_plan_acceptable(model_plan, request.prompt):
                return model_plan
        return strategy.create_plan(request)

    async def _repair_files_from_model_or_strategy(
        self,
        strategy,
        plan: ProjectPlan,
        failure_log: str,
        turn_input: TurnInput,
        *,
        task_digest: str = "",
    ) -> dict[str, str]:
        if self.model_editor is not None:
            try:
                repair_files = await self.model_editor.repair_files(
                    plan,
                    failure_log,
                    turn_input,
                    task_digest=task_digest,
                )
            except Exception:
                repair_files = {}
            if repair_files:
                return repair_files
        return strategy.repair_files(plan, failure_log)

    async def _publish(self, event) -> None:
        await self.event_bus.publish(event)


def _model_plan_acceptable(plan: ProjectPlan, prompt: str) -> bool:
    if project_plan_quality_errors(plan, prompt):
        return False
    if plan.language.lower() != "python" or not _featureful_python_cli_prompt(prompt):
        return True
    source_symbols = set().union(*planned_public_api_symbols(plan).values()) if plan.files else set()
    contract_symbols = _contract_symbol_names(source_symbols)
    if len(contract_symbols) < 4:
        return False
    if not _api_obligations_declared_in_plan(plan):
        return False
    test_content = "\n".join(file.content for file in plan.files if file.stage == "tests")
    if not test_content.strip():
        return False
    covered = {symbol for symbol in contract_symbols if symbol in test_content}
    return len(covered) >= 2


def _featureful_python_cli_prompt(prompt: str) -> bool:
    lowered = prompt.lower()
    compact = lowered.replace(" ", "")
    cli = any(term in lowered for term in ("cli", "command", "entrypoint", "argparse")) or any(
        term in prompt for term in ("명령어", "커맨드", "진입점")
    )
    feature = any(term in lowered or term in compact for term in ("registry", "retry", "json", "task", "export", "pytest")) or any(
        term in prompt for term in ("레지스트리", "재시도", "저장소", "테스트", "검증")
    )
    return cli and feature


def _contract_symbol_names(symbols: set[str]) -> set[str]:
    names: set[str] = set()
    for symbol in symbols:
        if symbol.startswith("__all__:"):
            symbol = symbol.split(":", 1)[1]
        if "." in symbol:
            owner, _, member = symbol.partition(".")
            names.add(owner)
            if len(member) > 2:
                names.add(member)
            continue
        if len(symbol) > 2:
            names.add(symbol)
    return names


def _api_obligations_declared_in_plan(plan: ProjectPlan) -> bool:
    if not plan.api_obligations:
        return True
    declared = declared_public_api_symbols(plan)
    for obligation in plan.api_obligations:
        symbols = declared.get(obligation.path, set())
        if not symbols or obligation.symbol not in symbols:
            return False
    return True


def _plan_summary(plan: ProjectPlan) -> str:
    """Human-readable plan preview shown for plan-mode approval."""
    lines = [f"대상 경로: {plan.target_root}", f"언어: {plan.language}", "", "생성/수정 예정 파일:"]
    for file in plan.files:
        lines.append(f"  - [{file.stage}] {file.path} — {file.purpose}")
    return "\n".join(lines)

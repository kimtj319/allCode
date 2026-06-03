"""Skeleton-first project generation workflow."""

from __future__ import annotations

from uuid import uuid4

from pydantic import Field

from allCode.agent.completion_checker import CompletionCheck, CompletionChecker
from allCode.agent.final_reporter import FinalReporter
from allCode.agent.project_planner import ModelProjectPlanner
from allCode.agent.router import RoutingDecision, RuleBasedRouter
from allCode.agent.task_plan import ProjectPlan
from allCode.agent.validation_runner import ValidationResult, ValidationRunner
from allCode.agent.workflow_actions import WorkflowActions, WorkflowStepRecord
from allCode.agent.workflow_routing import workflow_target_root_from_routing
from allCode.core.event_bus import AsyncEventBus, EventBus
from allCode.core.events import (
    GenerationWorkflowFinished,
    GenerationWorkflowStarted,
)
from allCode.core.models import CoreModel, TurnInput
from allCode.core.result import CompletionEvidence, ProjectManifest, RecoveryState, TurnResult
from allCode.generation.strategy import GenerationRequest, StrategyRegistry
from allCode.generation.strategies import default_strategy_registry
from allCode.llm.client import LLMClient
from allCode.llm.settings import ModelSettings
from allCode.tools.approval import ApprovalManager
from allCode.tools.builtin import builtin_tools
from allCode.tools.executor import ToolExecutor
from allCode.tools.registry import ToolRegistry


class GenerationWorkflowResult(CoreModel):
    plan: ProjectPlan
    turn_result: TurnResult
    validation_results: list[ValidationResult] = Field(default_factory=list)
    completion_check: CompletionCheck
    step_history: list[WorkflowStepRecord] = Field(default_factory=list)
    repair_attempts: int = 0


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
        model_planner: ModelProjectPlanner | None = None,
        max_repair_attempts: int = 5,
    ) -> None:
        self.strategy_registry = strategy_registry or default_strategy_registry()
        self.event_bus = event_bus or AsyncEventBus()
        self.router = router or RuleBasedRouter()
        self.validation_runner = validation_runner or ValidationRunner()
        self.completion_checker = completion_checker or CompletionChecker()
        self.final_reporter = final_reporter or FinalReporter()
        self.model_planner = model_planner or (
            ModelProjectPlanner(llm_client=llm_client, settings=settings)
            if llm_client is not None and settings is not None
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
        plan = await self._create_plan(request, routing=routing, strategy=strategy)
        completion_evidence = CompletionEvidence()
        recovery_states: list[RecoveryState] = []
        step_history: list[WorkflowStepRecord] = []
        validation_results: list[ValidationResult] = []
        repair_attempts = 0

        await self._publish(
            GenerationWorkflowStarted(
                turn_id=turn_id,
                message="Generation workflow started.",
                data={"target_root": plan.target_root, "language": plan.language},
            )
        )

        try:
            await self.actions.write_step_files("skeleton", plan, turn_input, turn_id, routing, completion_evidence, step_history)
            await self.actions.write_step_files("implementation", plan, turn_input, turn_id, routing, completion_evidence, step_history)
            await self.actions.write_step_files("tests", plan, turn_input, turn_id, routing, completion_evidence, step_history)

            validation_results.extend(
                await self._run_validation_step(plan, turn_input, turn_id, routing, completion_evidence, step_history)
            )

            if validation_results and validation_results[-1].ok:
                await self.actions.record_skipped_step("repair", turn_id, step_history, "Validation passed before repair.")
            else:
                repair_attempts = await self._repair_until_valid(
                    strategy=strategy,
                    plan=plan,
                    turn_input=turn_input,
                    turn_id=turn_id,
                    routing=routing,
                    completion_evidence=completion_evidence,
                    validation_results=validation_results,
                    recovery_states=recovery_states,
                    step_history=step_history,
                )

            preliminary_check = self.completion_checker.check(
                workspace_root=turn_input.workspace.root,
                plan=plan,
                completion_evidence=completion_evidence,
                validation_results=validation_results,
            )
            completion_evidence.project_manifest = self._build_project_manifest(
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

            if final_check.ok:
                completion_evidence.final_answer_ready = True
                completion_evidence.status = "reported"
                status = "success"
                error_message = None
            else:
                completion_evidence.final_answer_ready = False
                completion_evidence.status = "blocked"
                status = "failed"
                error_message = "Completion check failed: " + "; ".join(final_check.errors)
                final_report = ""

            await self._publish(
                GenerationWorkflowFinished(
                    turn_id=turn_id,
                    message="Generation workflow finished.",
                    data={"status": status, "errors": final_check.errors},
                )
            )
            return GenerationWorkflowResult(
                plan=plan,
                turn_result=TurnResult(
                    turn_id=turn_id,
                    status=status,
                    final_answer=final_report,
                    created_files=completion_evidence.created_files,
                    modified_files=completion_evidence.changed_files,
                    validation_passed=completion_evidence.validation_passed,
                    error_message=error_message,
                    completion_evidence=completion_evidence,
                    recovery_states=recovery_states,
                    requires_change_evidence=True,
                    validation_required=True,
                ),
                validation_results=validation_results,
                completion_check=final_check,
                step_history=step_history,
                repair_attempts=repair_attempts,
            )
        except Exception as exc:
            completion_evidence.status = "blocked"
            completion_evidence.final_answer_ready = False
            return GenerationWorkflowResult(
                plan=plan,
                turn_result=TurnResult(
                    turn_id=turn_id,
                    status="failed",
                    error_message=str(exc),
                    completion_evidence=completion_evidence,
                    recovery_states=recovery_states,
                    requires_change_evidence=True,
                    validation_required=True,
                ),
                validation_results=validation_results,
                completion_check=CompletionCheck(ok=False, errors=[str(exc)]),
                step_history=step_history,
                repair_attempts=repair_attempts,
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

    async def _create_plan(self, request: GenerationRequest, *, routing: RoutingDecision, strategy) -> ProjectPlan:
        target_hint = routing.target_hint or request.target_root
        if self.model_planner is not None:
            try:
                model_plan = await self.model_planner.create_plan(request.prompt, target_hint=target_hint)
            except Exception:
                model_plan = None
            if model_plan is not None:
                return model_plan
        return strategy.create_plan(request)

    async def _repair_until_valid(
        self,
        *,
        strategy,
        plan: ProjectPlan,
        turn_input: TurnInput,
        turn_id: str,
        routing: RoutingDecision,
        completion_evidence: CompletionEvidence,
        validation_results: list[ValidationResult],
        recovery_states: list[RecoveryState],
        step_history: list[WorkflowStepRecord],
    ) -> int:
        await self.actions.start_step("repair", turn_id, step_history, "Repairing validation failure.")
        attempts = 0
        previous_hash = validation_results[-1].error_hash if validation_results else None
        while validation_results and not validation_results[-1].ok and attempts < self.max_repair_attempts:
            failure = validation_results[-1]
            attempts += 1
            recovery_states.append(
                RecoveryState(reason="validation_failed", attempts=attempts, last_error=failure.summary or failure.error)
            )
            repair_files = strategy.repair_files(plan, failure.summary or failure.error or "")
            if not repair_files:
                recovery_states[-1] = recovery_states[-1].model_copy(update={"blocked": True})
                break
            await self.actions.write_repair_files(repair_files, plan, turn_input, turn_id, routing, completion_evidence)
            validation_results.extend(
                await self._run_validation_step(plan, turn_input, turn_id, routing, completion_evidence, step_history)
            )
            current_hash = validation_results[-1].error_hash
            if validation_results[-1].ok:
                break
            if current_hash and current_hash == previous_hash:
                recovery_states.append(
                    RecoveryState(
                        reason="validation_failed",
                        attempts=attempts,
                        last_error=validation_results[-1].summary or validation_results[-1].error,
                        blocked=True,
                    )
                )
                break
            previous_hash = current_hash
        status = "succeeded" if validation_results and validation_results[-1].ok else "failed"
        if attempts >= self.max_repair_attempts and validation_results and not validation_results[-1].ok:
            recovery_states.append(
                RecoveryState(
                    reason="validation_failed",
                    attempts=attempts,
                    last_error=validation_results[-1].summary or validation_results[-1].error,
                    blocked=True,
                )
            )
        await self.actions.finish_step("repair", turn_id, step_history, status, f"Repair attempts: {attempts}.")
        return attempts

    async def _publish(self, event) -> None:
        await self.event_bus.publish(event)

    def _build_project_manifest(
        self,
        *,
        plan: ProjectPlan,
        completion_evidence: CompletionEvidence,
    ) -> ProjectManifest:
        files = [planned_file.path for planned_file in plan.files]
        entrypoints = [
            f"{plan.target_root}/{path}"
            for path in files
            if path.endswith(("main.py", "cli.py", "__main__.py", "index.js", "main.go", "Main.java"))
            or "/cli" in path.lower()
        ]
        if not entrypoints:
            entrypoints = [
                f"{plan.target_root}/{path}"
                for path in files
                if path.endswith((".py", ".js", ".ts", ".go", ".rs", ".java")) and "test" not in path.lower()
            ][:3]
        test_paths = [f"{plan.target_root}/{path}" for path in files if "test" in path.lower() or "spec" in path.lower()]
        package_candidates = [
            f"{plan.target_root}/{path.rsplit('/', 1)[0]}"
            for path in files
            if "/" in path and "test" not in path.lower()
        ]
        package_root = package_candidates[0] if package_candidates else plan.target_root
        validation_commands = completion_evidence.validation_commands or [command.command for command in plan.validation_commands]
        validation_cwd = plan.validation_commands[0].cwd if plan.validation_commands else plan.target_root
        last_modified = [
            path
            for path in [*completion_evidence.created_files, *completion_evidence.changed_files]
            if path not in completion_evidence.deleted_files
        ]
        return ProjectManifest(
            project_root=plan.target_root,
            package_root=package_root,
            entrypoints=entrypoints,
            test_paths=test_paths,
            validation_commands=validation_commands,
            validation_cwd=validation_cwd,
            last_modified_files=last_modified,
            language=plan.language,
            confidence=0.85 if last_modified else 0.5,
        )

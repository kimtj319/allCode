"""Tool-backed generation workflow actions and step events."""

from __future__ import annotations

from uuid import uuid4

from allCode.agent.router import RoutingDecision
from allCode.agent.task_plan import GenerationStep, PlannedFile, ProjectPlan
from allCode.core.event_bus import EventBus
from allCode.core.events import GenerationStepFinished, GenerationStepStarted
from allCode.core.models import CoreModel, ToolCall, TurnInput
from allCode.core.result import CompletionEvidence
from allCode.tools.base import ToolContext
from allCode.tools.executor import ToolExecutor


class WorkflowStepRecord(CoreModel):
    step: GenerationStep
    status: str
    detail: str = ""


class WorkflowActions:
    def __init__(self, *, tool_executor: ToolExecutor, event_bus: EventBus) -> None:
        self.tool_executor = tool_executor
        self.event_bus = event_bus

    async def write_step_files(
        self,
        step: GenerationStep,
        plan: ProjectPlan,
        turn_input: TurnInput,
        turn_id: str,
        routing: RoutingDecision,
        completion_evidence: CompletionEvidence,
        step_history: list[WorkflowStepRecord],
    ) -> None:
        planned_files = plan.files_for_step(step) if step in {"skeleton", "implementation", "tests"} else []
        await self.start_step(step, turn_id, step_history, f"Writing {len(planned_files)} file(s).")
        for planned_file in planned_files:
            await self.write_file(planned_file, plan, turn_input, turn_id, routing, completion_evidence)
        await self.finish_step(step, turn_id, step_history, "succeeded", f"Wrote {len(planned_files)} file(s).")

    async def write_repair_files(
        self,
        files: dict[str, str],
        plan: ProjectPlan,
        turn_input: TurnInput,
        turn_id: str,
        routing: RoutingDecision,
        completion_evidence: CompletionEvidence,
    ) -> None:
        for relative_path, content in files.items():
            planned_file = PlannedFile(path=relative_path, purpose="repair output", stage="implementation", content=content)
            await self.write_file(planned_file, plan, turn_input, turn_id, routing, completion_evidence)

    async def write_file(
        self,
        planned_file: PlannedFile,
        plan: ProjectPlan,
        turn_input: TurnInput,
        turn_id: str,
        routing: RoutingDecision,
        completion_evidence: CompletionEvidence,
    ) -> None:
        call = ToolCall(
            id=f"write-{uuid4().hex[:10]}",
            name="write_file",
            arguments={"file_path": f"{plan.target_root}/{planned_file.path}", "content": planned_file.content},
        )
        result = await self.tool_executor.execute(
            call,
            ToolContext(
                workspace=turn_input.workspace,
                session_id=turn_input.session_id,
                turn_id=turn_id,
                approval_mode=self.tool_executor.approval_mode,
            ),
            routing=routing,
            completion_evidence=completion_evidence,
            event_bus=self.event_bus,
        )
        if not result.ok:
            raise RuntimeError(result.error or f"failed to write {planned_file.path}")

    async def record_skipped_step(
        self,
        step: GenerationStep,
        turn_id: str,
        step_history: list[WorkflowStepRecord],
        detail: str,
    ) -> None:
        await self.start_step(step, turn_id, step_history, detail)
        await self.finish_step(step, turn_id, step_history, "skipped", detail)

    async def start_step(self, step: GenerationStep, turn_id: str, step_history: list[WorkflowStepRecord], detail: str) -> None:
        step_history.append(WorkflowStepRecord(step=step, status="running", detail=detail))
        await self.event_bus.publish(
            GenerationStepStarted(
                turn_id=turn_id,
                message=f"Generation step started: {step}",
                data={"step": step, "detail": detail},
            )
        )

    async def finish_step(
        self,
        step: GenerationStep,
        turn_id: str,
        step_history: list[WorkflowStepRecord],
        status: str,
        detail: str,
    ) -> None:
        step_history.append(WorkflowStepRecord(step=step, status=status, detail=detail))
        await self.event_bus.publish(
            GenerationStepFinished(
                turn_id=turn_id,
                message=f"Generation step finished: {step}",
                data={"step": step, "status": status, "detail": detail},
            )
        )

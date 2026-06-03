"""Validation command candidate generation and execution."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import Field

from allCode.agent.router import RoutingDecision
from allCode.agent.task_plan import ProjectPlan, ValidationCommand
from allCode.agent.tool_evidence import ToolEvidenceRecorder
from allCode.agent.validation_repair import attach_validation_failure_summary
from allCode.core.event_bus import EventBus
from allCode.core.events import ToolCallRequested
from allCode.core.models import CoreModel, ToolCall, WorkspaceRef
from allCode.core.result import CompletionEvidence
from allCode.tools.base import ToolContext
from allCode.tools.executor import ToolExecutor


class ValidationResult(CoreModel):
    command: str
    cwd: str
    ok: bool
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    returncode: int | None = None
    error_hash: str | None = None
    summary: str = ""


class ValidationRunner:
    def __init__(self, *, max_log_chars: int = 8000) -> None:
        self.max_log_chars = max_log_chars
        self._evidence_recorder = ToolEvidenceRecorder()

    def candidates(self, plan: ProjectPlan) -> list[ValidationCommand]:
        if plan.validation_commands:
            return plan.validation_commands
        return self._infer_candidates(plan)

    async def run_all(
        self,
        *,
        plan: ProjectPlan,
        workspace: WorkspaceRef,
        session_id: str,
        turn_id: str,
        tool_executor: ToolExecutor,
        routing: RoutingDecision,
        completion_evidence: CompletionEvidence,
        event_bus: EventBus | None = None,
    ) -> list[ValidationResult]:
        results = []
        for command in self.candidates(plan):
            results.append(
                await self.run_command(
                    command=command,
                    workspace=workspace,
                    session_id=session_id,
                    turn_id=turn_id,
                    tool_executor=tool_executor,
                    routing=routing,
                    completion_evidence=completion_evidence,
                    event_bus=event_bus,
                )
            )
            if not results[-1].ok:
                break
        return results

    async def run_command(
        self,
        *,
        command: ValidationCommand,
        workspace: WorkspaceRef,
        session_id: str,
        turn_id: str,
        tool_executor: ToolExecutor,
        routing: RoutingDecision,
        completion_evidence: CompletionEvidence,
        event_bus: EventBus | None = None,
    ) -> ValidationResult:
        call = ToolCall(
            id=f"validation-{hashlib.sha256(command.command.encode('utf-8')).hexdigest()[:10]}",
            name="run_tests",
            arguments={
                "command": command.command,
                "cwd": command.cwd,
                "timeout_seconds": command.timeout_seconds,
            },
        )
        context = ToolContext(
            workspace=workspace,
            session_id=session_id,
            turn_id=turn_id,
            environment=command.environment,
            approval_mode="auto",
        )
        if event_bus is not None:
            await event_bus.publish(
                ToolCallRequested(
                    turn_id=turn_id,
                    message=f"Tool requested: {call.name}",
                    tool_call=call,
                )
            )
        tool_result = await tool_executor.execute(
            call,
            context,
            routing=routing,
            completion_evidence=completion_evidence,
            event_bus=event_bus,
        )
        tool_result = attach_validation_failure_summary(tool_result)
        self._evidence_recorder.record(tool_result, completion_evidence, workspace_root=workspace.root)
        stdout = str(tool_result.metadata.get("stdout", tool_result.content or ""))
        stderr = str(tool_result.metadata.get("stderr", tool_result.error or ""))
        log = stderr or stdout or tool_result.error or ""
        summary = self._summarize_log(log)
        return ValidationResult(
            command=command.command,
            cwd=command.cwd,
            ok=tool_result.ok,
            stdout=stdout[: self.max_log_chars],
            stderr=stderr[: self.max_log_chars],
            error=tool_result.error,
            returncode=tool_result.metadata.get("returncode") if isinstance(tool_result.metadata.get("returncode"), int) else None,
            error_hash=None if tool_result.ok else self._hash_log(log),
            summary=summary,
        )

    def _infer_candidates(self, plan: ProjectPlan) -> list[ValidationCommand]:
        paths = {planned_file.path for planned_file in plan.files}
        target = plan.target_root
        if "pyproject.toml" in paths or any(path.endswith(".py") for path in paths):
            return [ValidationCommand(command="python -m pytest", cwd=target, environment={"PYTHONPATH": "src"})]
        if "package.json" in paths:
            return [ValidationCommand(command="node --test", cwd=target)]
        if "go.mod" in paths:
            return [ValidationCommand(command="go test ./...", cwd=target)]
        if "Cargo.toml" in paths:
            return [ValidationCommand(command="cargo test", cwd=target)]
        java_files = [path for path in paths if path.endswith(".java")]
        if java_files:
            return [ValidationCommand(command="javac " + " ".join(sorted(java_files)), cwd=target)]
        return [
            ValidationCommand(
                command="python -c \"from pathlib import Path; assert any(Path('.').iterdir())\"",
                cwd=target,
            )
        ]

    def _summarize_log(self, log: str) -> str:
        lines = [line.rstrip() for line in log.splitlines() if line.strip()]
        if not lines:
            return ""
        failure_markers = (
            "FAILED",
            "ERROR",
            "Traceback",
            "AssertionError",
            "ZeroDivisionError",
            "CommandFailed",
            "E       ",
        )
        focused = [line for line in lines if any(marker in line for marker in failure_markers)]
        summary_lines = focused[:20] + [line for line in lines[:40] if line not in focused[:20]]
        summary_lines = summary_lines[:60]
        summary = "\n".join(summary_lines)
        if len(summary) > self.max_log_chars:
            return summary[: self.max_log_chars] + "\n[truncated]"
        return summary

    def _hash_log(self, log: str) -> str:
        normalized = "\n".join(line.strip() for line in log.splitlines() if line.strip())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

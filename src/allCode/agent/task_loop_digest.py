"""Compact implementation-loop task state for model calls."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import Field

from allCode.agent.router import RoutingDecision
from allCode.agent.task_plan import ProjectPlan
from allCode.core.models import CoreModel, Message, TurnInput
from allCode.core.result import CompletionEvidence, RecoveryState
from allCode.memory.redaction import redact_text

ValidationStatus = Literal["not_required", "pending", "failed", "passed"]


class TaskLoopDigest(CoreModel):
    user_goal: str
    route_kind: str
    accepted_plan: list[str] = Field(default_factory=list)
    completed_artifacts: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    created_files: list[str] = Field(default_factory=list)
    remaining_obligations: list[str] = Field(default_factory=list)
    validation_status: ValidationStatus = "pending"
    last_failure_excerpt: str | None = None
    next_required_action: str = ""

    def render(self) -> str:
        lines = [
            "Task loop digest for this model round:",
            f"- Original user goal: {self.user_goal}",
            f"- Route: {self.route_kind}",
        ]
        if self.accepted_plan:
            lines.append("- Accepted plan:")
            lines.extend(f"  - {item}" for item in self.accepted_plan[:8])
        if self.completed_artifacts:
            lines.append("- Completed artifacts:")
            lines.extend(f"  - {item}" for item in self.completed_artifacts[:10])
        if self.created_files or self.changed_files:
            lines.append("- File evidence:")
            for path in self.created_files[:8]:
                lines.append(f"  - created: {path}")
            for path in self.changed_files[:8]:
                lines.append(f"  - changed: {path}")
        if self.remaining_obligations:
            lines.append("- Remaining obligations:")
            lines.extend(f"  - {item}" for item in self.remaining_obligations[:10])
        lines.append(f"- Validation status: {self.validation_status}")
        if self.last_failure_excerpt:
            lines.append("- Latest failure excerpt:")
            lines.append(_indent(self.last_failure_excerpt[:900]))
        if self.next_required_action:
            lines.append(f"- Required next action: {self.next_required_action}")
        lines.append(
            "Use this digest as compact state. Do not expose hidden reasoning; act on the next required observable step."
        )
        return "\n".join(lines)


def build_task_loop_digest(
    *,
    turn_input: TurnInput,
    routing: RoutingDecision,
    evidence: CompletionEvidence,
    recovery_states: Sequence[RecoveryState] = (),
    plan: ProjectPlan | None = None,
    current_step: str = "",
    next_required_action: str = "",
) -> TaskLoopDigest:
    remaining = _remaining_obligations(evidence, plan)
    validation_status = _validation_status(routing, evidence)
    failure = evidence.validation_failure_excerpt or _latest_recovery_error(recovery_states)
    return TaskLoopDigest(
        user_goal=redact_text(_compact(turn_input.user_prompt, limit=700)),
        route_kind=routing.kind,
        accepted_plan=_accepted_plan(plan, current_step=current_step),
        completed_artifacts=_completed_artifacts(evidence),
        changed_files=[redact_text(path) for path in evidence.changed_files[:12]],
        created_files=[redact_text(path) for path in evidence.created_files[:12]],
        remaining_obligations=[redact_text(item) for item in remaining[:12]],
        validation_status=validation_status,
        last_failure_excerpt=redact_text(_compact(failure, limit=1000)) if failure else None,
        next_required_action=next_required_action or _default_next_action(routing, evidence, remaining, validation_status),
    )


def task_loop_digest_messages(messages: Sequence[Message], digest: TaskLoopDigest) -> list[Message]:
    """Return an outgoing message view with one compact digest system message."""

    digest_message = Message(
        role="system",
        content=digest.render(),
        metadata={"task_loop_digest": True},
    )
    filtered = [message for message in messages if not message.metadata.get("task_loop_digest")]
    insert_at = 0
    while insert_at < len(filtered) and filtered[insert_at].role == "system":
        insert_at += 1
    return [*filtered[:insert_at], digest_message, *filtered[insert_at:]]


def _accepted_plan(plan: ProjectPlan | None, *, current_step: str) -> list[str]:
    if plan is None:
        return [f"Current phase: {current_step}"] if current_step else []
    lines = [f"Target root: {plan.target_root}", f"Language: {plan.language}"]
    if current_step:
        lines.append(f"Current phase: {current_step}")
    for task in plan.tasks[:6]:
        lines.append(f"{task.step}: {task.description} [{task.status}]")
    if not plan.tasks:
        for file in plan.files[:8]:
            lines.append(f"{file.stage}: {file.path} - {file.purpose}")
    return lines


def _completed_artifacts(evidence: CompletionEvidence) -> list[str]:
    artifacts: list[str] = []
    for artifact in evidence.requested_artifacts:
        if artifact.satisfied:
            target = artifact.target or ", ".join(artifact.evidence_paths[:3]) or artifact.kind
            artifacts.append(f"{artifact.kind}: {target}")
    if evidence.validation_passed is True and evidence.validation_commands:
        artifacts.append("validation passed: " + evidence.validation_commands[-1])
    return artifacts


def _remaining_obligations(evidence: CompletionEvidence, plan: ProjectPlan | None) -> list[str]:
    obligations: list[str] = []
    for artifact in evidence.unsatisfied_artifacts():
        target = f": {artifact.target}" if artifact.target else ""
        reason = f" ({artifact.reason})" if artifact.reason else ""
        obligations.append(f"{artifact.kind}{target}{reason}")
    if evidence.feature_objectives:
        obligations.extend(f"feature objective: {objective}" for objective in evidence.feature_objectives[:8])
    if plan is not None:
        created_or_changed = set(evidence.created_files + evidence.changed_files)
        for path in plan.required_paths():
            full_suffix = f"/{path}"
            if not any(item.endswith(full_suffix) or item.endswith(path) for item in created_or_changed):
                obligations.append(f"required file: {path}")
    if evidence.has_file_change() and evidence.validation_passed is not True and evidence.validation_commands:
        obligations.append("rerun validation after the latest change")
    return _dedupe(obligations)


def _validation_status(routing: RoutingDecision, evidence: CompletionEvidence) -> ValidationStatus:
    if not routing.requires_validation:
        return "not_required"
    if evidence.validation_passed is True:
        return "passed"
    if evidence.validation_passed is False:
        return "failed"
    return "pending"


def _default_next_action(
    routing: RoutingDecision,
    evidence: CompletionEvidence,
    remaining: Sequence[str],
    validation_status: ValidationStatus,
) -> str:
    if remaining:
        return "Satisfy the first remaining obligation with an allowed mutation tool."
    if routing.requires_mutation and not evidence.has_file_change():
        return "Create or modify the requested files before any final answer."
    if validation_status in {"pending", "failed"}:
        return "Run validation or repair the latest validation failure before reporting success."
    return "Write the final answer grounded in completion evidence."


def _latest_recovery_error(recovery_states: Sequence[RecoveryState]) -> str:
    for state in reversed(recovery_states):
        if state.last_error:
            return state.last_error
    return ""


def _compact(text: str, *, limit: int) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return seen


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines() if line.strip())

"""Digest helpers for generation workflow model state."""

from __future__ import annotations

from allCode.agent.router import RoutingDecision
from allCode.agent.task_plan import ProjectPlan
from allCode.agent.task_loop_digest import TaskLoopDigest, build_task_loop_digest
from allCode.core.models import TurnInput
from allCode.core.result import CompletionEvidence, RecoveryState


def workflow_digest(
    turn_input: TurnInput,
    routing: RoutingDecision,
    completion_evidence: CompletionEvidence,
    *,
    recovery_states: list[RecoveryState] | None = None,
    plan: ProjectPlan,
    current_step: str,
    next_required_action: str,
) -> TaskLoopDigest:
    return build_task_loop_digest(
        turn_input=turn_input,
        routing=routing,
        evidence=completion_evidence,
        recovery_states=recovery_states or [],
        plan=plan,
        current_step=current_step,
        next_required_action=next_required_action,
    )

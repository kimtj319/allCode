"""Small obligation helpers used by ``AgentLoop``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from allCode.agent.phase_gate import seed_known_artifact_targets
from allCode.core.models import TurnInput
from allCode.core.result import CompletionEvidence
from allCode.memory.project_obligations import feature_objectives_from_prompt

if TYPE_CHECKING:
    from allCode.agent.context import ContextBuilder


def seed_session_artifact_obligations(
    turn_input: TurnInput,
    evidence: CompletionEvidence,
    routing: Any,
    context_builder: "ContextBuilder | None",
) -> None:
    if getattr(routing, "read_only_requested", False) or getattr(routing, "kind", "") in {"answer", "inspect"}:
        return
    for objective in feature_objectives_from_prompt(turn_input.user_prompt):
        if objective not in evidence.feature_objectives:
            evidence.feature_objectives.append(objective)
    if context_builder is None:
        return
    obligations = context_builder.session_state.active_project_obligations
    if obligations is None:
        return
    for objective in obligations.feature_objectives:
        if objective not in evidence.feature_objectives:
            evidence.feature_objectives.append(objective)
    seed_known_artifact_targets(
        turn_input.user_prompt,
        evidence,
        workspace_root=turn_input.workspace.root,
        source_files=obligations.source_files,
        test_files=obligations.test_files,
    )


def remember_generation_workflow_result(
    context_builder: "ContextBuilder | None",
    workflow_result: Any,
    *,
    workspace_root: str,
) -> None:
    if context_builder is None:
        return
    turn_result = workflow_result.turn_result
    for path in [*turn_result.created_files, *turn_result.modified_files]:
        context_builder.remember_target(path, turn_id=turn_result.turn_id, summary="generation workflow output")
    context_builder.session_state.remember_turn_outcome(
        turn_result.completion_evidence,
        status=turn_result.status,
        workspace_root=workspace_root,
    )


def target_hint_exists(workspace_root: str, target_hint: str) -> bool:
    candidate = Path(target_hint)
    if not candidate.is_absolute():
        candidate = Path(workspace_root) / candidate
    try:
        return candidate.expanduser().resolve().exists()
    except OSError:
        return False

"""Round repair-state calculations kept outside the main runner loop."""

from __future__ import annotations

from allCode.agent.phase_gate import mutation_artifact_required
from allCode.agent.recovery import RecoveryTracker
from allCode.agent.round_runtime import RoundRuntime
from allCode.agent.round_state import RoundStateSnapshot
from allCode.agent.validation_repair import validation_repair_needed
from allCode.core.models import TurnInput
from allCode.core.result import CompletionEvidence


def update_repair_flags(
    turn_input: TurnInput,
    routing,
    evidence: CompletionEvidence,
    runtime: RoundRuntime,
) -> bool:
    more_mutation = mutation_artifact_required(
        turn_input.user_prompt,
        evidence,
        workspace_root=turn_input.workspace.root,
        routing=routing,
    )
    if evidence.validation_passed is True:
        runtime.validation_action_pending = False
    if runtime.validation_action_pending or runtime.awaiting_revalidation_after_mutation:
        runtime.validation_repair_pending = False
    else:
        runtime.validation_repair_pending = runtime.validation_repair_pending or validation_repair_needed(routing, evidence)
    return more_mutation


def round_state_snapshot(
    round_index: int,
    evidence: CompletionEvidence,
    recovery: RecoveryTracker,
    runtime: RoundRuntime,
) -> RoundStateSnapshot:
    return RoundStateSnapshot(
        round_index=round_index,
        phase="normal",
        mutation_since_last_validation=evidence.has_file_change() and evidence.validation_passed is not True,
        validation_attempts=len(evidence.validation_commands),
        repair_attempts=recovery.validation_repair_requests,
        last_validation_status=evidence.validation_passed,
        mutation_attempted_after_failed_validation=runtime.mutation_attempted_after_failed_validation,
        mutation_succeeded_after_failed_validation=runtime.mutation_succeeded_after_failed_validation,
        last_validation_failure_symbols=list(evidence.validation_failure_symbols),
    )

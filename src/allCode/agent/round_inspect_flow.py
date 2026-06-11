"""Inspect-stage orchestration for model rounds."""

from __future__ import annotations

from allCode.agent.inspect_staging import decide_inspect_stage
from allCode.agent.round_runner_helpers import response_language
from allCode.agent.round_runtime import RoundRuntime
from allCode.core.events import InspectFinalizationGateOpened, InspectStageSelected
from allCode.core.models import TurnInput, TurnState
from allCode.core.result import CompletionEvidence


async def apply_inspect_stage(
    runner,
    *,
    turn_input: TurnInput,
    state: TurnState,
    runtime: RoundRuntime,
    evidence: CompletionEvidence,
    routing,
    round_index: int,
    inspect_round_budget: int,
):
    inspect_stage = decide_inspect_stage(
        prompt=turn_input.user_prompt,
        routing=routing,
        evidence=evidence,
        round_index=round_index,
        inspect_round_budget=inspect_round_budget,
        final_answer_requested=runtime.inspect_final_answer_requested,
    )
    if inspect_stage.active and runtime.last_inspect_stage != inspect_stage.stage:
        runtime.last_inspect_stage = inspect_stage.stage
        if inspect_stage.stage in {"source_discovery", "targeted_read"}:
            runtime.messages = runner._prompt_builder.inspect_stage_request(
                runtime.messages,
                stage=inspect_stage.stage,
                target_paths=inspect_stage.target_paths,
                reason=inspect_stage.reason,
            )
        await runner._publish(
            InspectStageSelected(
                turn_id=state.turn_id,
                message=f"Inspect stage selected: {inspect_stage.stage}.",
                data={
                    "round": round_index + 1,
                    "stage": inspect_stage.stage,
                    "reason": inspect_stage.reason,
                    "allowed_tools": sorted(inspect_stage.allowed_tool_names),
                    "target_paths": list(inspect_stage.target_paths),
                    "evidence_complete": inspect_stage.evidence_complete,
                },
            )
        )
    if (
        inspect_stage.stage == "finalize"
        and not runtime.inspect_final_answer_requested
        and evidence.inspect_observation_count > 0
    ):
        runtime.inspect_final_answer_requested = True
        await runner._publish(
            InspectFinalizationGateOpened(
                turn_id=state.turn_id,
                message="Inspect finalization gate opened.",
                data={
                    "round": round_index + 1,
                    "reason": inspect_stage.reason,
                    "source_overview_paths": list(evidence.source_overview_paths),
                    "inspected_paths": list(evidence.inspected_paths),
                    "search_candidate_paths": list(evidence.search_candidate_paths[:5]),
                },
            )
        )
        runtime.messages = runner._prompt_builder.source_analysis_final_answer_request(
            runtime.messages,
            response_language=response_language(turn_input.user_prompt),
        )
    return inspect_stage

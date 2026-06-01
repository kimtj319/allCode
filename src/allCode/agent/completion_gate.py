"""Completion evidence helpers for agent turn results."""

from __future__ import annotations

from allCode.agent.intent import IntentExtractor
from allCode.agent.router import RoutingDecision
from allCode.core.models import TurnInput, TurnState
from allCode.core.result import CompletionEvidence, ToolLoopSignature

_INTENT_EXTRACTOR = IntentExtractor()


def build_completion_evidence(
    *,
    turn_input: TurnInput,
    state: TurnState,
    outcome_status: str,
    outcome_answer: str,
    base_evidence: CompletionEvidence | None = None,
    routing: RoutingDecision | None = None,
) -> CompletionEvidence:
    requires_change = requires_change_evidence(turn_input.user_prompt, routing=routing)
    changed_files = _merge_unique(
        list(state.modified_files),
        list(base_evidence.changed_files if base_evidence is not None else []),
    )
    created_files = _merge_unique(
        list(state.created_files),
        list(base_evidence.created_files if base_evidence is not None else []),
    )
    file_change_present = bool(changed_files or created_files)
    final_answer_ready = outcome_status == "success" and bool(outcome_answer.strip())
    if requires_change and not file_change_present:
        final_answer_ready = False
    if final_answer_ready and file_change_present:
        status = "changed"
    elif final_answer_ready:
        status = "reported"
    elif outcome_status in {"failed", "partial"}:
        status = "blocked"
    else:
        status = "not_started"
    return CompletionEvidence(
        status=status,
        changed_files=changed_files,
        created_files=created_files,
        validation_commands=list(base_evidence.validation_commands if base_evidence is not None else []),
        validation_passed=base_evidence.validation_passed if base_evidence is not None else None,
        final_answer_ready=final_answer_ready,
    )


def requires_change_evidence(prompt: str, *, routing: RoutingDecision | None = None) -> bool:
    if routing is not None:
        return routing.kind == "modify" and routing.requires_mutation and not routing.read_only_requested
    signals = _INTENT_EXTRACTOR.extract(prompt)
    if signals.read_only_requested:
        return False
    return signals.modify_action


def tool_loop_signatures(loop_guard) -> list[ToolLoopSignature]:
    counts = getattr(loop_guard, "_counts", {})
    signatures_by_key = getattr(loop_guard, "signatures_by_key", {})
    signatures = []
    for key, count in counts.items():
        if count >= 3:
            signatures.append(
                signatures_by_key.get(
                    key,
                    ToolLoopSignature(tool_name="unknown", arguments_hash=key, count=count),
                )
            )
    return signatures


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged

"""Inspection budget calculations for model/tool rounds."""

from __future__ import annotations

from allCode.agent.source_inspection_budget import broad_source_scope, required_representative_probe_count
from allCode.core.result import CompletionEvidence


def inspection_budget_available(
    inspection_actions: int,
    inspection_rounds: int,
    *,
    default_action_budget: int,
    default_round_budget: int,
    action_budget: int | None = None,
    round_budget: int | None = None,
) -> bool:
    return inspection_actions < (action_budget or default_action_budget) and inspection_rounds < (
        round_budget or default_round_budget
    )


def effective_inspect_action_budget(
    prompt: str,
    routing,
    evidence: CompletionEvidence,
    *,
    default_budget: int,
) -> int:
    if not broad_source_inspect(prompt, routing, evidence):
        return default_budget
    required = required_source_probe_count(evidence)
    return min(9, max(default_budget, required + 1))


def effective_inspect_round_budget(
    prompt: str,
    routing,
    evidence: CompletionEvidence,
    *,
    default_budget: int,
    max_rounds: int,
) -> int:
    if not broad_source_inspect(prompt, routing, evidence):
        return default_budget
    required = required_source_probe_count(evidence)
    cap = max(default_budget, max_rounds - 1)
    return min(cap, max(default_budget, required + 1))


def broad_source_inspect(prompt: str, routing, evidence: CompletionEvidence) -> bool:
    if getattr(routing, "kind", "") != "inspect" or not getattr(routing, "read_only_requested", False):
        return False
    if evidence.source_representative_candidates or evidence.source_overview_truncated:
        return True
    if broad_source_scope(evidence):
        return True
    text = str(prompt or "").lower()
    return any(marker in text for marker in ("source tree", "directory structure", "module inventory", "package role"))


def required_source_probe_count(evidence: CompletionEvidence) -> int:
    return required_representative_probe_count(evidence)

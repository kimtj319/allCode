"""Validation repair public facade and phase state helpers."""

from __future__ import annotations

from enum import StrEnum

from allCode.agent.repair_target_ranking import rank_repair_targets
from allCode.agent.validation_failure_parser import (
    ValidationFailureSummary,
    attach_validation_failure_summary,
    summarize_validation_tool_result,
)
from allCode.core.result import CompletionEvidence

__all__ = [
    "RepairPhaseState",
    "ValidationFailureSummary",
    "attach_validation_failure_summary",
    "rank_repair_targets",
    "summarize_validation_tool_result",
    "validation_repair_needed",
]


class RepairPhaseState(StrEnum):
    NORMAL = "normal"
    VALIDATION_FAILED = "validation_failed"
    REPAIR_REQUIRED = "repair_required"
    MUTATION_DONE = "mutation_done"
    REVALIDATION_REQUIRED = "revalidation_required"
    REPAIR_EXHAUSTED = "repair_exhausted"


def validation_repair_needed(routing, evidence: CompletionEvidence) -> bool:
    return bool(
        routing.requires_validation
        and routing.requires_mutation
        and evidence.validation_passed is False
    )

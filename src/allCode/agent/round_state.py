"""Round state snapshots for validation and repair control."""

from __future__ import annotations

from typing import Literal

from allCode.core.models import CoreModel

RoundPhase = Literal[
    "normal",
    "inspection_required",
    "mutation_required",
    "test_authoring_required",
    "validation_required",
    "validation_failed",
    "repair_mutation_required",
    "revalidation_required",
    "repair_exhausted",
]

RequiredNextAction = Literal[
    "none",
    "inspect",
    "mutate",
    "write_tests",
    "validate",
    "repair",
    "revalidate",
    "report_partial",
]


class RoundStateSnapshot(CoreModel):
    round_index: int
    phase: RoundPhase = "normal"
    last_action_kind: str = ""
    mutation_since_last_validation: bool = False
    validation_attempts: int = 0
    repair_attempts: int = 0
    last_validation_status: bool | None = None
    mutation_attempted_after_failed_validation: bool = False
    mutation_succeeded_after_failed_validation: bool = False
    last_validation_failure_symbols: list[str] = []
    required_next_action: RequiredNextAction = "none"

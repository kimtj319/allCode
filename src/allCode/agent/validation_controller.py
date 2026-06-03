"""Deterministic validation and repair phase decisions."""

from __future__ import annotations

from pydantic import Field

from allCode.agent.round_state import RequiredNextAction, RoundPhase, RoundStateSnapshot
from allCode.agent.validation_repair import validation_repair_needed
from allCode.core.models import CoreModel
from allCode.core.result import CompletionEvidence


class ValidationControlDecision(CoreModel):
    phase: RoundPhase = "normal"
    required_next_action: RequiredNextAction = "none"
    validation_action_pending: bool = False
    validation_repair_pending: bool = False
    mutation_action_pending: bool = False
    awaiting_revalidation_after_mutation: bool = False
    repair_exhausted: bool = False
    should_inject_validation_action: bool = False
    reason: str = ""
    allowed_tool_names: set[str] = Field(default_factory=set)


class ValidationRepairController:
    """Converts evidence and recovery counters into explicit next-action decisions."""

    def __init__(self, *, max_repair_attempts: int = 2) -> None:
        self.max_repair_attempts = max_repair_attempts

    def decide(
        self,
        *,
        snapshot: RoundStateSnapshot,
        routing,
        evidence: CompletionEvidence,
        validation_action_pending: bool,
        validation_repair_pending: bool,
        mutation_action_pending: bool,
        awaiting_revalidation_after_mutation: bool,
        more_mutation_before_validation: bool,
        validation_action_requested: bool,
        max_rounds: int,
    ) -> ValidationControlDecision:
        if not getattr(routing, "requires_validation", False) or not getattr(routing, "requires_mutation", False):
            return ValidationControlDecision(
                phase=snapshot.phase,
                required_next_action=snapshot.required_next_action,
                mutation_action_pending=mutation_action_pending,
            )
        if evidence.validation_passed is True:
            return ValidationControlDecision(
                phase="normal",
                required_next_action="none",
                validation_action_pending=False,
                validation_repair_pending=False,
                mutation_action_pending=False,
                awaiting_revalidation_after_mutation=False,
                reason="validation already passed",
            )
        if (
            snapshot.last_validation_status is False
            and not snapshot.mutation_succeeded_after_failed_validation
            and not awaiting_revalidation_after_mutation
        ):
            if snapshot.repair_attempts >= self.max_repair_attempts:
                return ValidationControlDecision(
                    phase="repair_exhausted",
                    required_next_action="report_partial",
                    repair_exhausted=True,
                    reason="validation repair attempts are exhausted",
                )
            return ValidationControlDecision(
                phase="repair_mutation_required",
                required_next_action="repair",
                validation_repair_pending=True,
                mutation_action_pending=True,
                reason="validation failed and a repair mutation is required before revalidation",
                allowed_tool_names={"read_file", "search_files", "list_directory", "patch_file", "write_file"},
            )
        if validation_repair_needed(routing, evidence) and not awaiting_revalidation_after_mutation:
            if snapshot.repair_attempts >= self.max_repair_attempts:
                return ValidationControlDecision(
                    phase="repair_exhausted",
                    required_next_action="report_partial",
                    repair_exhausted=True,
                    reason="validation repair attempts are exhausted",
                )
            return ValidationControlDecision(
                phase="repair_mutation_required",
                required_next_action="repair",
                validation_repair_pending=True,
                mutation_action_pending=True,
                reason="validation failed and repair mutation is required",
                allowed_tool_names={"read_file", "search_files", "list_directory", "patch_file", "write_file"},
            )
        if validation_action_pending or awaiting_revalidation_after_mutation:
            return ValidationControlDecision(
                phase="revalidation_required" if awaiting_revalidation_after_mutation else "validation_required",
                required_next_action="revalidate" if awaiting_revalidation_after_mutation else "validate",
                validation_action_pending=True,
                awaiting_revalidation_after_mutation=awaiting_revalidation_after_mutation,
                should_inject_validation_action=self._should_inject(
                    snapshot.round_index,
                    max_rounds=max_rounds,
                    validation_action_requested=validation_action_requested,
                ),
                reason="validation is pending after file mutation",
                allowed_tool_names={"run_tests"},
            )
        if evidence.has_file_change() and not more_mutation_before_validation:
            return ValidationControlDecision(
                phase="validation_required",
                required_next_action="validate",
                validation_action_pending=True,
                should_inject_validation_action=self._should_inject(
                    snapshot.round_index,
                    max_rounds=max_rounds,
                    validation_action_requested=validation_action_requested,
                ),
                reason="file changes require validation",
                allowed_tool_names={"run_tests"},
            )
        if more_mutation_before_validation:
            return ValidationControlDecision(
                phase="test_authoring_required",
                required_next_action="write_tests",
                mutation_action_pending=True,
                reason="test artifact is required before validation",
                allowed_tool_names={"read_file", "search_files", "list_directory", "patch_file", "write_file"},
            )
        return ValidationControlDecision(
            phase=snapshot.phase,
            required_next_action=snapshot.required_next_action,
            validation_action_pending=validation_action_pending,
            validation_repair_pending=validation_repair_pending,
            mutation_action_pending=mutation_action_pending,
            awaiting_revalidation_after_mutation=awaiting_revalidation_after_mutation,
        )

    @staticmethod
    def _should_inject(round_index: int, *, max_rounds: int, validation_action_requested: bool) -> bool:
        return validation_action_requested or round_index >= max_rounds - 2

"""Session-scoped agent runtime state shared across turns."""

from __future__ import annotations

from allCode.agent.tool_action_ledger import ToolActionLedger
from allCode.agent.tool_orchestrator import ObservationCache, ToolBudgetTracker
from allCode.core.result import CompletionEvidence
from allCode.memory.project_obligations import (
    ActiveProjectObligations,
    LatestRepairContext,
    active_obligations_from_evidence,
    repair_context_from_evidence,
)


class AgentSessionState:
    """Holds reusable read-only observations and tool accounting for one session."""

    def __init__(
        self,
        *,
        observation_cache: ObservationCache | None = None,
        tool_budget: ToolBudgetTracker | None = None,
        action_ledger: ToolActionLedger | None = None,
    ) -> None:
        self.observation_cache = observation_cache or ObservationCache()
        self.tool_budget = tool_budget or ToolBudgetTracker()
        self.action_ledger = action_ledger or ToolActionLedger()
        self.active_project_obligations: ActiveProjectObligations | None = None
        self.latest_repair_context: LatestRepairContext | None = None

    def remember_turn_outcome(self, evidence: CompletionEvidence, *, status: str, workspace_root: str = "") -> None:
        obligations = active_obligations_from_evidence(evidence, workspace_root=workspace_root)
        if status in {"partial", "failed"} and obligations.feature_objectives:
            pending = "Pending feature objectives: " + ", ".join(obligations.feature_objectives[:8])
            if pending not in obligations.unsatisfied_conditions:
                obligations.unsatisfied_conditions.append(pending)
        if obligations.render():
            self.active_project_obligations = self._merge_obligations(self.active_project_obligations, obligations)
        if evidence.validation_passed is True:
            if self.active_project_obligations is not None:
                self.active_project_obligations.unsatisfied_conditions = [
                    condition
                    for condition in self.active_project_obligations.unsatisfied_conditions
                    if not condition.startswith("Pending feature objectives:")
                ]
            self.latest_repair_context = None
            return
        if status in {"partial", "failed"} and (
            evidence.validation_failure_targets
            or evidence.validation_failure_symbols
            or evidence.validation_failure_excerpt
        ):
            self.latest_repair_context = repair_context_from_evidence(evidence)

    @staticmethod
    def _merge_obligations(
        current: ActiveProjectObligations | None,
        incoming: ActiveProjectObligations,
    ) -> ActiveProjectObligations:
        if current is None:
            return incoming
        return ActiveProjectObligations(
            source_files=_merge_unique(current.source_files, incoming.source_files)[:8],
            test_files=_merge_unique(current.test_files, incoming.test_files)[:8],
            validation_commands=_merge_unique(current.validation_commands, incoming.validation_commands)[-3:],
            feature_objectives=_merge_unique(current.feature_objectives, incoming.feature_objectives)[:12],
            unsatisfied_conditions=_merge_unique(current.unsatisfied_conditions, incoming.unsatisfied_conditions)[:8],
        )


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for item in right:
        if item and item not in merged:
            merged.append(item)
    return merged

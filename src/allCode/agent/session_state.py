"""Session-scoped agent runtime state shared across turns."""

from __future__ import annotations

from allCode.agent.tool_action_ledger import ToolActionLedger
from allCode.agent.tool_orchestrator import ObservationCache, ToolBudgetTracker
from allCode.core.result import CompletionEvidence
from allCode.memory.project_obligations import (
    ActiveProjectObligations,
    LatestRepairContext,
    SourceExplorationLedger,
    active_obligations_from_evidence,
    repair_context_from_evidence,
    source_exploration_ledger_from_evidence,
)
from allCode.memory.session_state_store import (
    SessionStateSnapshot,
    build_freshness_metadata,
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
        self.source_exploration_ledger: SourceExplorationLedger | None = None

    def remember_turn_outcome(self, evidence: CompletionEvidence, *, status: str, workspace_root: str = "") -> None:
        ledger = source_exploration_ledger_from_evidence(evidence, workspace_root=workspace_root)
        if ledger.render():
            self.source_exploration_ledger = self._merge_source_ledger(self.source_exploration_ledger, ledger)
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
        if status == "success" and not (
            evidence.validation_failure_targets
            or evidence.validation_failure_symbols
            or evidence.validation_failure_excerpt
        ):
            self.latest_repair_context = None
            return
        if status in {"partial", "failed"} and (
            evidence.validation_failure_targets
            or evidence.validation_failure_symbols
            or evidence.validation_failure_excerpt
        ):
            self.latest_repair_context = repair_context_from_evidence(evidence)

    def to_snapshot(self, *, session_id: str, workspace_root: str) -> SessionStateSnapshot:
        return SessionStateSnapshot(
            session_id=session_id,
            active_project_obligations=self.active_project_obligations,
            latest_repair_context=self.latest_repair_context,
            source_exploration_ledger=self.source_exploration_ledger,
            file_freshness=build_freshness_metadata(
                self._freshness_paths(),
                workspace_root=workspace_root,
            ),
        )

    def load_snapshot(self, snapshot: SessionStateSnapshot) -> None:
        self.active_project_obligations = snapshot.active_project_obligations
        self.source_exploration_ledger = snapshot.source_exploration_ledger
        stale = set(snapshot.stale_paths)
        repair = snapshot.latest_repair_context
        if repair is not None and stale:
            fresh_targets = [target for target in repair.targets if target.file_path not in stale]
            repair = repair.model_copy(update={"targets": fresh_targets})
            if not repair.targets and not repair.symbols and not repair.excerpt:
                repair = None
            self._record_stale_snapshot_note(sorted(stale))
        self.latest_repair_context = repair

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

    @staticmethod
    def _merge_source_ledger(
        current: SourceExplorationLedger | None,
        incoming: SourceExplorationLedger,
    ) -> SourceExplorationLedger:
        if current is None:
            return incoming
        observed = _merge_unique(current.observed_scopes, incoming.observed_scopes)
        representatives = _merge_unique(current.representative_files, incoming.representative_files)
        representative_set = set(representatives)
        unobserved = [
            path
            for path in _merge_unique(current.unobserved_candidates, incoming.unobserved_candidates)
            if path not in representative_set
        ]
        coverage_note = incoming.coverage_note or current.coverage_note
        return SourceExplorationLedger(
            observed_scopes=observed[:10],
            representative_files=representatives[:12],
            unobserved_candidates=unobserved[:8],
            coverage_note=coverage_note,
        )

    def _freshness_paths(self) -> list[str]:
        paths: list[str] = []
        if self.active_project_obligations is not None:
            paths.extend(self.active_project_obligations.source_files)
            paths.extend(self.active_project_obligations.test_files)
        if self.latest_repair_context is not None:
            paths.extend(target.file_path for target in self.latest_repair_context.targets)
        if self.source_exploration_ledger is not None:
            paths.extend(self.source_exploration_ledger.representative_files)
        return _merge_unique([], paths)

    def _record_stale_snapshot_note(self, stale_paths: list[str]) -> None:
        note = "Stale persisted repair targets ignored: " + ", ".join(stale_paths[:3])
        if self.source_exploration_ledger is None:
            self.source_exploration_ledger = SourceExplorationLedger(coverage_note=note)
            return
        existing = self.source_exploration_ledger.coverage_note
        if note in existing:
            return
        coverage_note = f"{existing}; {note}".strip("; ") if existing else note
        if len(coverage_note) > 700:
            coverage_note = coverage_note[-700:].lstrip("; ")
        self.source_exploration_ledger = self.source_exploration_ledger.model_copy(update={"coverage_note": coverage_note})


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for item in right:
        if item and item not in merged:
            merged.append(item)
    return merged

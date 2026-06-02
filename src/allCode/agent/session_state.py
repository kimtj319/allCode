"""Session-scoped agent runtime state shared across turns."""

from __future__ import annotations

from allCode.agent.tool_action_ledger import ToolActionLedger
from allCode.agent.tool_orchestrator import ObservationCache, ToolBudgetTracker


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

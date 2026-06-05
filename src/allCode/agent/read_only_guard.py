"""Read-only route invariants for tool execution boundaries."""

from __future__ import annotations

from allCode.agent.policy import ToolPolicy
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolDefinition

READ_ONLY_BLOCKED_CATEGORIES = {"mutation", "shell", "validation"}


def read_only_tool_denial(
    *,
    routing,
    tool_call: ToolCall,
    policy: ToolPolicy,
    definition: ToolDefinition | None = None,
) -> ToolResult | None:
    if routing is None or not getattr(routing, "read_only_requested", False):
        return None
    category = policy.category_for_tool(tool_call.name)
    if category == "unknown" and definition is not None:
        category = "read" if definition.read_only else "mutation"
    if category not in READ_ONLY_BLOCKED_CATEGORIES:
        return None
    reason = (
        "Read-only request blocks this tool. "
        "The file-changing, shell, or validation action was ignored so the turn can continue as read-only analysis."
    )
    return ToolResult(
        call_id=tool_call.id,
        name=tool_call.name,
        ok=False,
        error=reason,
        error_type="policy_denied",
        metadata={
            "category": category,
            "read_only_invariant_violation": True,
            "blocked_tool": tool_call.name,
            "observation": {
                "kind": "policy_denied",
                "target": tool_call.name,
                "summary": reason,
                "risk": "low",
            },
        },
    )

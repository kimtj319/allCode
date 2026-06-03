"""Standard schema-denied result/event helper for tool calls."""

from __future__ import annotations

from allCode.agent.phase_gate import PhaseToolGate
from allCode.agent.policy import ToolPolicy
from allCode.core.event_bus import EventBus
from allCode.core.events import ToolCallSchemaDenied
from allCode.core.models import ToolCall, ToolResult


async def deny_tool_schema(
    *,
    event_bus: EventBus,
    turn_id: str,
    tool_call: ToolCall,
    policy: ToolPolicy,
    allowed_tool_names: set[str] | None,
    phase_gate: PhaseToolGate | None,
    reason: str,
) -> ToolResult:
    next_action = phase_gate.required_next_action if phase_gate is not None else ""
    phase_reason = phase_gate.reason if phase_gate is not None else ""
    if next_action and "Required next action:" not in reason:
        reason = f"{reason} Required next action: {next_action}"
    category = policy.category_for_tool(tool_call.name)
    await event_bus.publish(
        ToolCallSchemaDenied(
            turn_id=turn_id,
            message=f"Tool schema denied: {tool_call.name}.",
            tool_call=tool_call,
            data={
                "tool_name": tool_call.name,
                "allowed_tools": sorted(allowed_tool_names or []),
                "reason": reason,
                "phase": phase_gate.phase if phase_gate is not None else None,
                "phase_reason": phase_reason,
                "required_next_action": next_action,
                "category": category,
            },
        )
    )
    return ToolResult(
        call_id=tool_call.id,
        name=tool_call.name,
        ok=False,
        error=reason,
        error_type="schema_denied",
        metadata={
            "category": category,
            "allowed_tools": sorted(allowed_tool_names or []),
            "phase": phase_gate.phase if phase_gate is not None else None,
            "phase_reason": phase_reason,
            "required_next_action": next_action,
            "observation": {
                "kind": "schema_denied",
                "target": tool_call.name,
                "summary": reason,
                "risk": "low",
            },
        },
    )

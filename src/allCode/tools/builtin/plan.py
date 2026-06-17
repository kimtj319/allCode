"""Live task-plan tracking tool (Codex/Claude-Code-style progress checklist).

The model calls ``update_plan`` with the full ordered step list and each step's
status on every update; the latest call replaces the plan. The TUI renders it as
a visible checklist so the user can follow a multi-step task in real time."""

from __future__ import annotations

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition

_STATUS_ICON = {"completed": "✔", "in_progress": "▶", "pending": "☐"}
_VALID_STATUS = set(_STATUS_ICON)


class UpdatePlanTool:
    definition = ToolDefinition(
        name="update_plan",
        description=(
            "Maintain a short, user-visible task checklist for a multi-step task. "
            "Call this at the start of a non-trivial task with the planned steps, and "
            "again whenever a step's status changes (mark exactly one step in_progress). "
            "Send the FULL ordered step list every time; the latest call replaces the plan. "
            "Skip it for trivial one-step requests."
        ),
        parameters={
            "type": "object",
            "properties": {
                "plan": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string", "description": "Short imperative description of the step."},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        },
                        "required": ["step", "status"],
                        "additionalProperties": False,
                    },
                },
                "explanation": {"type": "string", "description": "Optional one-line note about the update."},
            },
            "required": ["plan"],
            "additionalProperties": False,
        },
        read_only=True,
        requires_approval=False,
        group="general",
        output_mode="log",
        idempotent=True,
    )

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        raw_plan = call.arguments.get("plan")
        if not isinstance(raw_plan, list) or not raw_plan:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error="plan must be a non-empty array of {step, status} items",
                error_type="invalid_plan",
            )
        steps: list[dict[str, str]] = []
        for item in raw_plan:
            if not isinstance(item, dict):
                continue
            step = str(item.get("step", "")).strip()
            status = str(item.get("status", "pending")).strip().lower()
            if not step:
                continue
            if status not in _VALID_STATUS:
                status = "pending"
            steps.append({"step": step, "status": status})
        if not steps:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error="plan contained no valid steps",
                error_type="invalid_plan",
            )
        explanation = str(call.arguments.get("explanation", "")).strip()
        done = sum(1 for s in steps if s["status"] == "completed")
        checklist = "\n".join(f"  {_STATUS_ICON[s['status']]} {s['step']}" for s in steps)
        content = f"계획 ({done}/{len(steps)})\n{checklist}"
        if explanation:
            content = f"{content}\n  · {explanation}"
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=content,
            metadata={
                "plan": steps,
                "completed": done,
                "total": len(steps),
                "explanation": explanation,
                "observation": {
                    "kind": "plan",
                    "target": "",
                    "summary": f"Plan updated: {done}/{len(steps)} step(s) complete",
                    "risk": "low",
                },
            },
        )

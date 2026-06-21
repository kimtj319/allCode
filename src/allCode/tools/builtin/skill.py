"""The ``skill`` tool: load a user-defined skill's instructions on demand.

Skill names + descriptions live in this tool's own description (always visible to
the model under the unified loop), so the model knows what skills exist; it calls
``skill(name)`` to pull the full instructions only when one is relevant —
progressive disclosure without bloating every prompt.
"""

from __future__ import annotations

from allCode.core.event_bus import EventBus
from allCode.core.models import ToolCall, ToolResult
from allCode.tools.base import ToolContext, ToolDefinition


class SkillTool:
    def __init__(self, config) -> None:
        from allCode.workspace.skills import load_skill_definitions

        self._skills = {s.name: s for s in load_skill_definitions(config.workspace.root)}
        listing = "; ".join(f"{name}: {s.description}" for name, s in self._skills.items())
        self.definition = ToolDefinition(
            name="skill",
            description=(
                "Load a user-defined skill's full instructions, then follow them. "
                "Call this when a listed skill fits the current task. "
                f"Available skills — {listing or 'none'}."
            ),
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Name of the skill to load."}},
                "required": ["name"],
                "additionalProperties": False,
            },
            read_only=True,
            requires_approval=False,
            group="agent",
        )

    @property
    def has_skills(self) -> bool:
        return bool(self._skills)

    async def run(self, call: ToolCall, context: ToolContext, event_bus: EventBus | None = None) -> ToolResult:
        name = str((call.arguments or {}).get("name", "")).strip().lower()
        skill = self._skills.get(name)
        if skill is None:
            available = ", ".join(self._skills) or "none"
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error=f"unknown skill: {name!r}; available: {available}",
                error_type="unknown_skill",
            )
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=skill.instructions,
            metadata={"skill": name},
        )

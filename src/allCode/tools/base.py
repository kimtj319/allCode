"""Tool contracts shared by registry and agent loop."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import Field

from allCode.core.event_bus import EventBus
from allCode.core.models import CoreModel, ToolCall, ToolResult, WorkspaceRef


class ToolDefinition(CoreModel):
    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True
    requires_approval: bool = False
    group: str = "general"
    aliases: list[str] = Field(default_factory=list)


class ToolContext(CoreModel):
    workspace: WorkspaceRef
    session_id: str
    turn_id: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    approval_mode: str = "ask"


class BaseTool(Protocol):
    definition: ToolDefinition

    async def run(
        self,
        call: ToolCall,
        context: ToolContext,
        event_bus: EventBus | None = None,
    ) -> ToolResult:
        raise NotImplementedError("tools must implement run")


def tool_schema(definition: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": definition.name,
            "description": definition.description,
            "parameters": definition.parameters,
        },
    }


class StaticTextTool:
    """Small reusable tool for tests and local smoke scenarios."""

    def __init__(self, name: str, content: str, *, read_only: bool = True) -> None:
        self.definition = ToolDefinition(
            name=name,
            description=f"Return static text for {name}.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            read_only=read_only,
        )
        self._content = content

    async def run(
        self,
        call: ToolCall,
        context: ToolContext,
        event_bus: EventBus | None = None,
    ) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            content=self._content,
            metadata={"arguments": call.arguments},
        )

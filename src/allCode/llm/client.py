"""Provider-neutral LLM client contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from allCode.core.events import ModelEvent
from pydantic import Field

from allCode.core.models import CoreModel, Message, TokenUsage, ToolCall
from allCode.llm.settings import ModelSettings, ToolSchema


class ModelResponse(CoreModel):
    final_text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    status: str = "ok_text"


class LLMClient(Protocol):
    def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        settings: ModelSettings,
    ) -> AsyncIterator[ModelEvent]:
        raise NotImplementedError("LLM clients must stream model events")

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        settings: ModelSettings,
    ) -> ModelResponse:
        raise NotImplementedError("LLM clients must return a complete model response")

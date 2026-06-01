"""Scriptable fake LLM client used by unit and integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass

from allCode.core.events import ModelEvent, ModelToolCallDelta
from allCode.core.models import Message, TokenUsage, ToolCall
from allCode.llm.client import ModelResponse
from allCode.llm.response_parser import ResponseParser
from allCode.llm.settings import ModelSettings, ToolSchema


@dataclass(frozen=True)
class StreamDelay:
    seconds: float


StreamItem = ModelEvent | StreamDelay


class FakeLLMClient:
    """Deterministic LLM client that returns scripted model event sequences."""

    def __init__(
        self,
        scenarios: Iterable[Iterable[StreamItem]] | None = None,
        *,
        default_text: str = "I am ready.",
    ) -> None:
        self._scenarios = [list(events) for events in scenarios or []]
        self._default_text = default_text
        self.calls = 0

    @classmethod
    def text(cls, text: str) -> "FakeLLMClient":
        return cls([cls.text_events(text)])

    @classmethod
    def tool_then_text(cls, tool_call: ToolCall, text: str) -> "FakeLLMClient":
        return cls([cls.tool_call_events(tool_call), cls.text_events(text)])

    @classmethod
    def reasoning_only_then_final(cls, text: str) -> "FakeLLMClient":
        return cls([cls.reasoning_only_events(), cls.text_events(text)])

    @classmethod
    def empty_twice(cls) -> "FakeLLMClient":
        return cls([cls.empty_events(), cls.empty_events()], default_text="")

    @classmethod
    def slow_then_text(cls, text: str, *, delay_seconds: float) -> "FakeLLMClient":
        return cls([[StreamDelay(delay_seconds), *cls.text_events(text)]])

    @classmethod
    def slow_then_tool(
        cls,
        tool_call: ToolCall,
        *,
        delay_seconds: float,
    ) -> "FakeLLMClient":
        return cls([[StreamDelay(delay_seconds), *cls.tool_call_events(tool_call)]])

    @classmethod
    def same_tool_three_times(cls, tool_call: ToolCall, final_text: str) -> "FakeLLMClient":
        return cls(
            [
                cls.tool_call_events(tool_call),
                cls.tool_call_events(tool_call),
                cls.tool_call_events(tool_call),
                cls.text_events(final_text),
            ]
        )

    @staticmethod
    def text_events(text: str) -> list[ModelEvent]:
        return [
            ModelEvent(kind="text_delta", text=text),
            ModelEvent(kind="response_completed", finish_reason="stop"),
        ]

    @staticmethod
    def empty_events() -> list[ModelEvent]:
        return [ModelEvent(kind="response_completed", finish_reason="stop")]

    @staticmethod
    def reasoning_only_events() -> list[ModelEvent]:
        return [
            ModelEvent(kind="text_delta", text="", metadata={"reasoning_delta": "private"}),
            ModelEvent(kind="response_completed", finish_reason="stop"),
        ]

    @staticmethod
    def length_cutoff_events(text: str = "partial") -> list[ModelEvent]:
        return [
            ModelEvent(kind="text_delta", text=text),
            ModelEvent(kind="response_completed", finish_reason="length"),
        ]

    @staticmethod
    def malformed_tool_call_events() -> list[ModelEvent]:
        return [
            ModelEvent(
                kind="tool_call_delta",
                tool_call_delta=ModelToolCallDelta(
                    id="call-malformed",
                    name="lookup",
                    arguments_delta='{"q": "abc"',
                ),
            ),
            ModelEvent(kind="response_completed", finish_reason="tool_calls"),
        ]

    @staticmethod
    def tool_call_events(tool_call: ToolCall) -> list[ModelEvent]:
        return [
            ModelEvent(kind="tool_call_completed", tool_call=tool_call),
            ModelEvent(kind="response_completed", finish_reason="tool_calls"),
        ]

    async def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        settings: ModelSettings,
    ) -> AsyncIterator[ModelEvent]:
        scenario_index = self.calls
        self.calls += 1
        if scenario_index < len(self._scenarios):
            events = self._scenarios[scenario_index]
        else:
            prompt = next((message.content for message in reversed(messages) if message.role == "user"), "")
            text = self._default_text if not prompt else f"{self._default_text} {prompt}".strip()
            events = self.text_events(text)
        for event in events:
            if isinstance(event, StreamDelay):
                await asyncio.sleep(event.seconds)
            else:
                yield event

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        settings: ModelSettings,
    ) -> ModelResponse:
        events = [event async for event in self.stream(messages, tools, settings)]
        parsed = ResponseParser().parse_events(events)
        return ModelResponse(
            final_text=parsed.text,
            tool_calls=parsed.tool_calls,
            finish_reason=parsed.finish_reason,
            usage=parsed.usage or TokenUsage(),
            status=parsed.status,
        )

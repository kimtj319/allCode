"""LLM client decorator that tallies token usage per model.

Wraps any :class:`LLMClient` and records the token usage of every
``complete()`` call into a :class:`UsageStore`, keyed by ``settings.model_name``.
This is how the /status gauge attributes usage to the separate models the agent
runs (e.g. the ultra routing/planning model vs the implementation/max editor
model): the router, project planner, and file editor all reach the provider
through ``complete()``.

Streaming (``stream()``) is passed through untouched — the round runner already
emits its own per-round usage via the ``ModelMetricsRecorded`` event, so
recording it here too would double count."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from allCode.core.events import ModelEvent
from allCode.core.models import Message
from allCode.llm.client import LLMClient, ModelResponse
from allCode.llm.settings import ModelSettings, ToolSchema
from allCode.memory.usage_store import UsageStore


class UsageRecordingLLMClient:
    """Transparent LLMClient wrapper that records ``complete()`` token usage."""

    def __init__(self, inner: LLMClient, usage_store: UsageStore) -> None:
        self._inner = inner
        self._usage = usage_store

    def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        settings: ModelSettings,
    ) -> AsyncIterator[ModelEvent]:
        # Stream usage is recorded by the round runner's metrics event; pass through.
        return self._inner.stream(messages, tools, settings)

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        settings: ModelSettings,
    ) -> ModelResponse:
        response = await self._inner.complete(messages, tools, settings)
        self._record(response, settings)
        return response

    def _record(self, response: ModelResponse, settings: ModelSettings) -> None:
        usage = response.usage
        total = int(getattr(usage, "total_tokens", 0) or 0)
        if total <= 0:
            total = int(getattr(usage, "prompt_tokens", 0) or 0) + int(getattr(usage, "completion_tokens", 0) or 0)
        if total <= 0:
            return
        self._usage.add(total, model=settings.model_name)

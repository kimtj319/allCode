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

from allCode.core.event_bus import EventBus
from allCode.core.events import ModelEvent, ModelInvoked
from allCode.core.models import Message
from allCode.llm.client import LLMClient, ModelResponse
from allCode.llm.settings import ModelSettings, ToolSchema
from allCode.memory.usage_store import UsageStore


class UsageRecordingLLMClient:
    """Transparent LLMClient wrapper that records ``complete()`` token usage.

    Also announces which model each ``complete()`` used via a ``ModelInvoked``
    event when an event bus is supplied, so the UI can show the active tier
    (e.g. the base model for routing/planning vs the implementation model for
    code edits). Streaming rounds are announced separately by the round runner."""

    def __init__(self, inner: LLMClient, usage_store: UsageStore, *, event_bus: EventBus | None = None) -> None:
        self._inner = inner
        self._usage = usage_store
        self._event_bus = event_bus

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
        await self._announce(settings)
        return response

    async def _announce(self, settings: ModelSettings) -> None:
        if self._event_bus is None or not settings.model_name:
            return
        try:
            await self._event_bus.publish(
                ModelInvoked(message="Model invoked.", data={"model": settings.model_name})
            )
        except Exception:  # noqa: BLE001 - telemetry must never break a model call
            pass

    def _record(self, response: ModelResponse, settings: ModelSettings) -> None:
        usage = response.usage
        total = int(getattr(usage, "total_tokens", 0) or 0)
        if total <= 0:
            total = int(getattr(usage, "prompt_tokens", 0) or 0) + int(getattr(usage, "completion_tokens", 0) or 0)
        if total <= 0:
            return
        self._usage.add(total, model=settings.model_name)

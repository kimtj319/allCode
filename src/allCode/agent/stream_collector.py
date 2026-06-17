"""Model stream collection with heartbeat and timeout recovery."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from allCode.agent.recovery import RecoveryTracker
from allCode.core.event_bus import EventBus
from allCode.core.events import ModelStreamHeartbeat, ModelStreamTimedOut, ModelTextDelta, RecoveryStateUpdated
from allCode.core.models import Message, TurnState
from allCode.llm.client import LLMClient
from allCode.llm.settings import ModelSettings, ToolSchema


class ModelStreamCollector:
    """Collects provider events while keeping progress visible to TUI/headless users."""

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        settings: ModelSettings,
        event_bus: EventBus,
        heartbeat_interval_seconds: float,
        stream_timeout_seconds: float,
    ) -> None:
        self._llm_client = llm_client
        self._settings = settings
        self._event_bus = event_bus
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._stream_timeout_seconds = stream_timeout_seconds

    @property
    def model_name(self) -> str:
        """Model name this collector streams from (for per-model usage tally)."""
        return self._settings.model_name

    async def collect(
        self,
        *,
        state: TurnState,
        messages: Sequence[Message],
        recovery: RecoveryTracker,
        tool_schemas: Sequence[ToolSchema],
        stream_text: bool = True,
    ) -> tuple[list, bool]:
        iterator = self._llm_client.stream(messages, tool_schemas, self._settings).__aiter__()
        events = []
        heartbeat_count = 0
        started_at = asyncio.get_running_loop().time()
        next_event_task = asyncio.create_task(anext(iterator))
        while True:
            elapsed = asyncio.get_running_loop().time() - started_at
            remaining_timeout = max(0.0, self._stream_timeout_seconds - elapsed)
            if remaining_timeout <= 0:
                await self._record_recovery(
                    state,
                    recovery,
                    "stream_timeout",
                    attempts=heartbeat_count,
                    blocked=not bool(events),
                )
                await self._event_bus.publish(
                    ModelStreamTimedOut(
                        turn_id=state.turn_id,
                        message="Model stream timed out.",
                    )
                )
                next_event_task.cancel()
                return events, True
            wait_seconds = min(self._heartbeat_interval_seconds, remaining_timeout)
            done, _pending = await asyncio.wait({next_event_task}, timeout=wait_seconds)
            if not done:
                heartbeat_count += 1
                await self._record_recovery(state, recovery, "slow_stream", attempts=heartbeat_count)
                await self._event_bus.publish(
                    ModelStreamHeartbeat(
                        turn_id=state.turn_id,
                        message="Model stream heartbeat.",
                        data={"heartbeat_count": heartbeat_count},
                    )
                )
                continue
            try:
                event = next_event_task.result()
            except StopAsyncIteration:
                return events, False
            events.append(event)
            next_event_task = asyncio.create_task(anext(iterator))
            if stream_text and event.kind == "text_delta" and event.text:
                await self._event_bus.publish(
                    ModelTextDelta(
                        turn_id=state.turn_id,
                        message=event.text,
                        delta=event.text,
                    )
                )

    async def _record_recovery(
        self,
        state: TurnState,
        recovery: RecoveryTracker,
        reason,
        *,
        attempts: int = 0,
        last_error: str | None = None,
        blocked: bool = False,
    ) -> None:
        recovery.add_state(reason, attempts=attempts, last_error=last_error, blocked=blocked)
        latest = recovery.states[-1]
        await self._event_bus.publish(
            RecoveryStateUpdated(
                turn_id=state.turn_id,
                message=f"Recovery state updated: {latest.reason}.",
                data=latest.model_dump(mode="json"),
            )
        )

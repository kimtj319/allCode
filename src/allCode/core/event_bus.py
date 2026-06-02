"""Async event bus used between agent loop and user interfaces."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from allCode.core.events import AgentEvent, EventDropped

EventHandler = Callable[[AgentEvent], Awaitable[None]]
Unsubscribe = Callable[[], None]


class EventBus(Protocol):
    async def publish(self, event: AgentEvent) -> None:
        raise NotImplementedError("EventBus implementations must publish events")

    def subscribe(
        self,
        event_type: type[AgentEvent] | None,
        handler: EventHandler,
    ) -> Unsubscribe:
        raise NotImplementedError("EventBus implementations must subscribe handlers")

    async def close(self, *, drain: bool = True) -> None:
        raise NotImplementedError("EventBus implementations must close cleanly")


class AsyncEventBus:
    """Queue-backed event bus that preserves publish order within a process."""

    def __init__(self, *, maxsize: int = 1000) -> None:
        self._queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue(maxsize=maxsize)
        self._subscribers: list[tuple[type[AgentEvent] | None, EventHandler]] = []
        self._worker: asyncio.Task[None] | None = None
        self._closed = False
        self._dropped_count = 0

    def subscribe(
        self,
        event_type: type[AgentEvent] | None,
        handler: EventHandler,
    ) -> Unsubscribe:
        subscriber = (event_type, handler)
        self._subscribers.append(subscriber)

        def unsubscribe() -> None:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

        return unsubscribe

    async def publish(self, event: AgentEvent) -> None:
        if self._closed:
            raise RuntimeError("event bus is closed")
        self._ensure_worker()
        if self._queue.full() and event.severity != "user_visible":
            self._dropped_count += 1
            return
        await self._queue.put(event)

    async def close(self, *, drain: bool = True) -> None:
        if self._closed:
            return
        if drain:
            await self._queue.join()
            if self._dropped_count:
                dropped = self._dropped_count
                self._dropped_count = 0
                await self._queue.put(
                    EventDropped(
                        turn_id="event-bus",
                        message="Low-priority events were dropped due to backpressure.",
                        dropped_count=dropped,
                    )
                )
                await self._queue.join()
        else:
            self._clear_queue()
        self._closed = True
        await self._queue.put(None)
        if self._worker is not None:
            await self._worker

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run(), name="allCode-event-bus")

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                if event is None:
                    return
                await self._deliver(event)
            finally:
                self._queue.task_done()

    async def _deliver(self, event: AgentEvent) -> None:
        subscribers = list(self._subscribers)
        for event_type, handler in subscribers:
            if event_type is None or isinstance(event, event_type):
                try:
                    await handler(event)
                except Exception:
                    self._dropped_count += 1

    def _clear_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                return

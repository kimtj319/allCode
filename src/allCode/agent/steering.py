"""Mid-turn steering queue.

Lets the user inject extra guidance into a turn that is already running. The
TUI pushes a typed message while the agent works; the round runner drains the
queue at each round boundary and feeds the messages in as additional user
turns, so the next model round sees the correction without cancelling and
restarting. Thread-safe because the TUI captures input on a separate thread
from the agent's event loop.
"""

from __future__ import annotations

import threading


class SteeringQueue:
    def __init__(self) -> None:
        self._messages: list[str] = []
        self._lock = threading.Lock()

    def push(self, message: str) -> None:
        text = (message or "").strip()
        if not text:
            return
        with self._lock:
            self._messages.append(text)

    def drain(self) -> list[str]:
        """Return and clear all pending steering messages."""
        with self._lock:
            pending = self._messages
            self._messages = []
        return pending

    def pending(self) -> bool:
        with self._lock:
            return bool(self._messages)

"""Prompt history navigation for the terminal composer."""

from __future__ import annotations


class TerminalHistory:
    """In-memory prompt history with a transient draft slot."""

    def __init__(self) -> None:
        self._entries: list[str] = []
        self._index: int | None = None
        self._draft = ""

    def append(self, text: str) -> None:
        normalized = text.strip("\n")
        if not normalized:
            self.reset_navigation()
            return
        if not self._entries or self._entries[-1] != normalized:
            self._entries.append(normalized)
        self.reset_navigation()

    def previous(self, current: str) -> str | None:
        if not self._entries:
            return None
        if self._index is None:
            self._draft = current
            self._index = len(self._entries) - 1
        elif self._index > 0:
            self._index -= 1
        return self._entries[self._index]

    def next(self) -> str | None:
        if self._index is None:
            return None
        if self._index >= len(self._entries) - 1:
            value = self._draft
            self.reset_navigation()
            return value
        self._index += 1
        return self._entries[self._index]

    def reset_navigation(self) -> None:
        self._index = None
        self._draft = ""

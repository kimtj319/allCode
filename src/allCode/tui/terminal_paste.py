"""Paste handling for the terminal composer."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from allCode.tui.terminal_text_area import TerminalTextArea
from allCode.tui.terminal_paste_sanitizer import normalize_pasted_text

LARGE_PASTE_CHAR_THRESHOLD = 1000


@dataclass(frozen=True)
class PendingPaste:
    placeholder: str
    text: str


class PasteManager:
    """Track large paste placeholders and expand them at submission time."""

    def __init__(self, *, threshold: int = LARGE_PASTE_CHAR_THRESHOLD) -> None:
        self.threshold = threshold
        self._pending: list[PendingPaste] = []
        self._issued_counts: dict[int, int] = {}

    @property
    def pending(self) -> list[PendingPaste]:
        return list(self._pending)

    def clear(self) -> None:
        self._pending.clear()
        self._issued_counts.clear()

    def insert_paste(self, area: TerminalTextArea, pasted: str) -> None:
        normalized = normalize_pasted_text(pasted)
        if len(normalized) > self.threshold:
            placeholder = self._next_placeholder(len(normalized))
            self._pending.append(PendingPaste(placeholder=placeholder, text=normalized))
            area.insert_element(placeholder, kind="large_paste")
            return
        area.insert(normalized)

    def prune(self, visible_text: str, *, element_labels: Iterable[str] | None = None) -> None:
        if element_labels is not None:
            labels = set(element_labels)
            self._pending = [entry for entry in self._pending if entry.placeholder in labels]
            return
        self._pending = [entry for entry in self._pending if entry.placeholder in visible_text]

    def expand(self, visible_text: str) -> str:
        expanded = visible_text
        for entry in self._pending:
            expanded = expanded.replace(entry.placeholder, entry.text, 1)
        return expanded

    def _next_placeholder(self, char_count: int) -> str:
        base = f"[Pasted Content {char_count} chars]"
        count = self._issued_counts.get(char_count, 0) + 1
        self._issued_counts[char_count] = count
        if count == 1:
            return base
        return f"{base} #{count}"

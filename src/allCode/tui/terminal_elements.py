"""Atomic text elements for terminal composer placeholders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ElementKind = Literal["large_paste", "file_reference", "attachment"]


@dataclass
class TextRange:
    start: int
    end: int

    def contains(self, index: int) -> bool:
        return self.start < index < self.end

    def overlaps(self, start: int, end: int) -> bool:
        return self.start < end and start < self.end


@dataclass
class TextElement:
    id: int
    range: TextRange
    kind: ElementKind
    label: str


@dataclass(frozen=True)
class TextElementSnapshot:
    id: int
    start: int
    end: int
    kind: ElementKind
    label: str

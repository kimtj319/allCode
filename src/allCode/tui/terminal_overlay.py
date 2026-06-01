"""Transient overlay state for the terminal bottom pane."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from allCode.tui.terminal_frame import StyledLine

OverlayKind = Literal["completion", "shortcut", "history"]


@dataclass(frozen=True)
class OverlayItem:
    label: str
    description: str = ""
    selected: bool = False


@dataclass(frozen=True)
class OverlayView:
    kind: OverlayKind
    items: list[OverlayItem] = field(default_factory=list)

    def render_lines(self, *, max_lines: int = 5) -> list[StyledLine]:
        lines: list[StyledLine] = []
        for item in self.items[:max_lines]:
            marker = ">" if item.selected else " "
            suffix = f" - {item.description}" if item.description else ""
            lines.append(StyledLine(text=f"{marker} {item.label}{suffix}", style="dim"))
        return lines

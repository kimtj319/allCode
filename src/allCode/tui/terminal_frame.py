"""Render DTOs for the terminal bottom pane."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StyledLine:
    text: str
    style: str = "normal"


@dataclass(frozen=True)
class TerminalFrame:
    input_lines: list[StyledLine]
    cursor_row: int
    cursor_col: int
    overlay_lines: list[StyledLine] = field(default_factory=list)
    footer_lines: list[StyledLine] = field(default_factory=list)
    activity_lines: list[StyledLine] = field(default_factory=list)
    spacer_after_activity: bool = False

    @property
    def line_count(self) -> int:
        spacer = 1 if self.spacer_after_activity and self.activity_lines else 0
        return len(self.activity_lines) + spacer + len(self.input_lines) + len(self.overlay_lines) + len(self.footer_lines)

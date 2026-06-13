"""Transcript state for committed and active TUI cells."""

from __future__ import annotations

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.tui.transcript_cells import TranscriptCell, assistant_cell, streaming_assistant_cell


class TranscriptState(CoreModel):
    committed_cells: list[TranscriptCell] = Field(default_factory=list)
    active_cell: TranscriptCell | None = None
    overlays: list[TranscriptCell] = Field(default_factory=list)

    def clear(self) -> None:
        self.committed_cells.clear()
        self.active_cell = None
        self.overlays.clear()

    def commit(self, cell: TranscriptCell) -> None:
        self.committed_cells.append(cell)

    def ensure_active_assistant(self) -> TranscriptCell:
        if self.active_cell is None:
            self.active_cell = streaming_assistant_cell("")
        return self.active_cell

    def append_active_delta(self, delta: str) -> None:
        active = self.ensure_active_assistant()
        self.active_cell = active.append(delta)

    def finalize_active(self, final_content: str | None = None) -> None:
        if self.active_cell is None:
            if final_content:
                self.commit(assistant_cell(final_content))
            return
        content = final_content if final_content is not None and final_content.strip() else self.active_cell.content
        if content.strip():
            self.commit(assistant_cell(content.strip()))
        self.active_cell = None

    def visible_cells(self) -> list[TranscriptCell]:
        cells = list(self.committed_cells)
        if self.active_cell is not None:
            cells.append(self.active_cell)
        cells.extend(self.overlays)
        return cells

"""Codex-style transcript view for Textual."""

from __future__ import annotations

import time
from collections.abc import Sequence

from allCode.tui.message_widgets import make_cell_widget, update_cell_widget
from allCode.tui.transcript_cells import TranscriptCell

try:
    from textual.containers import VerticalScroll

    TEXTUAL_VIEW_AVAILABLE = True
except ModuleNotFoundError:
    VerticalScroll = object
    TEXTUAL_VIEW_AVAILABLE = False


if TEXTUAL_VIEW_AVAILABLE:

    class TranscriptView(VerticalScroll):
        """Render transcript cells without rebuilding the entire transcript."""

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._cell_ids: list[str] = []
            self._follow_output = True
            self._last_scroll_at = 0.0

        def sync_cells(self, cells: Sequence[TranscriptCell], *, force_follow: bool = False) -> None:
            ids = [cell.id for cell in cells]
            should_follow = force_follow or self._should_follow_output()
            self._sync_positionally(cells)
            self._cell_ids = ids
            if should_follow:
                self._follow_output = True
                self._scroll_to_end_throttled()

        def mark_user_scrolled(self) -> None:
            if not self.is_vertical_scroll_end:
                self._follow_output = False

        def resume_following(self) -> None:
            self._follow_output = True
            self._scroll_to_end_throttled(force=True)

        def _sync_positionally(self, cells: Sequence[TranscriptCell]) -> None:
            widgets = list(self.children)
            shared_count = min(len(widgets), len(cells))

            for index in range(shared_count):
                update_cell_widget(widgets[index], cells[index])

            for cell in cells[shared_count:]:
                widget = make_cell_widget(cell)
                self.mount(widget)

            for widget in widgets[len(cells) :]:
                widget.remove()

        def _should_follow_output(self) -> bool:
            return self._follow_output or self.is_vertical_scroll_end

        def _scroll_to_end_throttled(self, *, force: bool = False) -> None:
            now = time.monotonic()
            if not force and now - self._last_scroll_at < 0.05:
                return
            self._last_scroll_at = now
            self.call_after_refresh(self.scroll_end, animate=False, immediate=True)

else:

    class TranscriptView:
        def sync_cells(self, cells: Sequence[TranscriptCell], *, force_follow: bool = False) -> None:
            return None

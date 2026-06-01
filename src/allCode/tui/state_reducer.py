"""Pure-ish reducer helpers for TUI layout state."""

from __future__ import annotations

from allCode.tui.event_bridge import UIEvent
from allCode.tui.markdown_stream_state import MarkdownStreamState
from allCode.tui.transcript_cells import error_cell, status_cell, tool_cell
from allCode.tui.transcript_state import TranscriptState


class TUIStateReducer:
    """Apply UI events to transcript state without importing Textual widgets."""

    def __init__(self, stream_state: MarkdownStreamState | None = None) -> None:
        self.stream_state = stream_state or MarkdownStreamState()

    def reset_stream(self) -> None:
        self.stream_state.reset()

    def apply(self, transcript: TranscriptState, event: UIEvent) -> None:
        if event.kind == "assistant_delta_received":
            visible = self.stream_state.append(event.content)
            if visible:
                transcript.active_cell = transcript.ensure_active_assistant().with_content(visible)
            return
        if event.kind == "assistant_finalized":
            flushed = self.stream_state.flush()
            transcript.finalize_active(event.content.strip() or flushed.strip())
            return
        if event.kind == "tool_result_committed":
            transcript.commit(tool_cell(event.content, title="Tool"))
            return
        if event.kind == "turn_failed_visible":
            transcript.commit(error_cell(event.content))
            return
        if event.kind == "approval_opened":
            transcript.commit(status_cell(event.content, title="Approval"))
            return
        if event.content and event.kind == "footer_status_changed":
            transcript.commit(status_cell(event.content))

"""TUI layout state independent from agent internals."""

from __future__ import annotations

from pydantic import Field

from allCode.core.events import AgentEvent
from allCode.core.models import CoreModel
from allCode.tui import messages
from allCode.tui.event_bridge import TUIEventBridge
from allCode.tui.markdown_normalizer import normalize_agent_markdown
from allCode.tui.renderers import EventRenderer, FoldedToolOutput
from allCode.tui.state_reducer import TUIStateReducer
from allCode.tui.transcript_cells import (
    cell_to_legacy_block,
    error_cell,
    format_legacy_block,
    status_cell,
    tool_cell,
    user_cell,
)
from allCode.tui.transcript_state import TranscriptState

TRANSCRIPT_LABELS = {
    "user": "USER",
    "allCode": "ALLCODE",
    "tool": "TOOL",
    "approval": "APPROVAL",
    "error": "ERROR",
    "status": "STATUS",
}


class TUILayoutState(CoreModel):
    transcript: list[str] = Field(default_factory=list)
    transcript_cells: TranscriptState = Field(default_factory=TranscriptState)
    status: str = messages.READY_STATUS
    input_enabled: bool = True
    spinner_active: bool = False
    turn_running: bool = False
    queued_inputs: list[str] = Field(default_factory=list)
    steer_messages: list[str] = Field(default_factory=list)
    folds: list[FoldedToolOutput] = Field(default_factory=list)
    streaming_answer_index: int | None = None


class TUIStateController:
    def __init__(self, renderer: EventRenderer | None = None) -> None:
        self.renderer = renderer or EventRenderer()
        self.bridge = TUIEventBridge(self.renderer)
        self.reducer = TUIStateReducer()
        self.state = TUILayoutState()

    def submit_prompt(self, prompt: str) -> None:
        if self.state.turn_running:
            self.queue_prompt(prompt)
            return
        self.state.input_enabled = True
        self.state.turn_running = True
        self.state.spinner_active = True
        self.state.status = messages.MODEL_REQUEST_STATUS
        self.state.streaming_answer_index = None
        self.reducer.reset_stream()
        self.state.transcript_cells.commit(user_cell(prompt))
        self._sync_legacy_transcript()

    def queue_prompt(self, prompt: str) -> None:
        if prompt:
            self.state.queued_inputs.append(prompt)
            self.state.status = f"{len(self.state.queued_inputs)} queued · Enter to steer · Tab to queue"

    def steer_prompt(self, prompt: str) -> None:
        if not prompt:
            return
        self.state.steer_messages.append(prompt)
        # Until the runtime exposes a true mid-turn injection channel, preserve
        # the user's intent by scheduling the steering text as the next turn.
        self.state.queued_inputs.append(prompt)
        self.state.status = "추가 지시를 기록했습니다 · 현재 turn 이후 이어서 처리합니다"

    def handle_event(self, event: AgentEvent) -> None:
        ui_event = self.bridge.from_agent_event(event)
        self._apply_ui_event(ui_event.kind, ui_event.content)
        rendered = self.renderer.render(event)
        if ui_event.status:
            self.state.status = ui_event.status
        elif rendered.status:
            self.state.status = rendered.status
        self.state.spinner_active = ui_event.spinner
        if rendered.foldable:
            self.state.folds.append(
                FoldedToolOutput(
                    title=rendered.fold_title or "tool output",
                    preview=rendered.transcript[:800],
                    full_text=rendered.fold_full_text or rendered.transcript,
                )
            )
        if event.event_type in {"final_answer_ready", "turn_failed", "turn_cancelled", "generation_workflow_finished"}:
            self.recover_input()

    def append_message(self, role: str, content: str) -> None:
        if content:
            self._append_legacy_and_cell(role, content)

    def clear_transcript(self) -> None:
        self.state.transcript.clear()
        self.state.transcript_cells.clear()
        self.state.streaming_answer_index = None
        self.reducer.reset_stream()
        self.state.status = messages.READY_STATUS
        self.recover_input()

    def finish_local_command(self) -> None:
        self.state.status = messages.READY_STATUS
        self.recover_input()

    def recover_input(self) -> None:
        self.state.input_enabled = True
        self.state.turn_running = False
        self.state.spinner_active = False
        if not self.state.status:
            self.state.status = messages.READY_STATUS

    def next_queued_input(self) -> str | None:
        if not self.state.queued_inputs:
            return None
        return self.state.queued_inputs.pop(0)

    def clear_queued_inputs(self) -> None:
        self.state.queued_inputs.clear()

    def _append_stream_delta(self, delta: str) -> None:
        if not delta:
            return
        visible_content = self.reducer.stream_state.append(delta)
        if not visible_content:
            return
        self._replace_active_stream(visible_content)

    def _append_visible_stream_delta(self, delta: str) -> None:
        current = self.state.transcript_cells.ensure_active_assistant().content
        self._replace_active_stream(current + delta)

    def _replace_active_stream(self, content: str) -> None:
        self.state.transcript_cells.active_cell = self.state.transcript_cells.ensure_active_assistant().with_content(content)
        self._sync_legacy_transcript()
        self.state.streaming_answer_index = len(self.state.transcript) - 1

    def _finalize_answer(self, answer: str) -> None:
        flushed = self.reducer.stream_state.flush()
        final_answer = normalize_agent_markdown(answer.strip() or flushed.strip())
        self.state.transcript_cells.finalize_active(final_answer or None)
        self._sync_legacy_transcript()
        self.state.streaming_answer_index = None

    def _append_legacy_and_cell(self, role: str, content: str) -> None:
        if role == "user":
            self.state.transcript_cells.commit(user_cell(content))
        elif role == "allCode":
            self.state.transcript_cells.finalize_active(content)
        elif role == "tool":
            self.state.transcript_cells.commit(tool_cell(content))
        elif role == "error":
            self.state.transcript_cells.commit(error_cell(content))
        else:
            self.state.transcript_cells.commit(status_cell(content))
        self._sync_legacy_transcript()

    def _sync_legacy_transcript(self) -> None:
        self.state.transcript = [cell_to_legacy_block(cell) for cell in self.state.transcript_cells.visible_cells()]

    def _apply_ui_event(self, kind: str, content: str) -> None:
        if kind == "assistant_delta_received":
            self._append_stream_delta(content)
            return
        if kind == "assistant_finalized":
            self._finalize_answer(content)
            return
        if kind == "tool_result_committed":
            self._append_legacy_and_cell("tool", content)
            return
        if kind == "turn_failed_visible":
            self._append_legacy_and_cell("error", content)
            return
        if kind == "approval_opened":
            self._append_legacy_and_cell("approval", content)
            return
        if kind == "footer_status_changed" and content:
            self._append_legacy_and_cell("status", content)


def format_transcript_block(role: str, content: str) -> str:
    return format_legacy_block(role, content)


def transcript_block_content(block: str) -> str:
    lines = block.strip("\n").splitlines()
    if len(lines) <= 1:
        return ""
    return "\n".join(line[2:] if line.startswith("  ") else line for line in lines[1:])

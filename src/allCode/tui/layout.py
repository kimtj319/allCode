"""TUI layout state independent from agent internals."""

from __future__ import annotations

from pydantic import Field

from allCode.core.events import AgentEvent
from allCode.core.models import CoreModel
from allCode.tui import messages
from allCode.tui.renderers import EventRenderer, FoldedToolOutput
from allCode.tui.streaming import MarkdownStreamBuffer

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
    status: str = messages.READY_STATUS
    input_enabled: bool = True
    spinner_active: bool = False
    queued_inputs: list[str] = Field(default_factory=list)
    folds: list[FoldedToolOutput] = Field(default_factory=list)
    streaming_answer_index: int | None = None


class TUIStateController:
    def __init__(self, renderer: EventRenderer | None = None) -> None:
        self.renderer = renderer or EventRenderer()
        self.state = TUILayoutState()
        self.stream_buffer = MarkdownStreamBuffer()

    def submit_prompt(self, prompt: str) -> None:
        if self.state.input_enabled:
            self.state.input_enabled = False
            self.state.spinner_active = True
            self.state.status = messages.MODEL_REQUEST_STATUS
            self.state.streaming_answer_index = None
            self.stream_buffer.reset()
            self.state.transcript.append(format_transcript_block("user", prompt))
            return
        self.state.queued_inputs.append(prompt)

    def queue_prompt(self, prompt: str) -> None:
        if prompt:
            self.state.queued_inputs.append(prompt)

    def handle_event(self, event: AgentEvent) -> None:
        rendered = self.renderer.render(event)
        if rendered.transcript_role == "allCode_stream":
            self._append_stream_delta(rendered.transcript)
        elif event.event_type == "final_answer_ready":
            self._finalize_answer(rendered.transcript)
        elif rendered.transcript:
            self.state.transcript.append(format_transcript_block(rendered.transcript_role, rendered.transcript))
        if rendered.status:
            self.state.status = rendered.status
        self.state.spinner_active = rendered.spinner
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
            self.state.transcript.append(format_transcript_block(role, content))

    def clear_transcript(self) -> None:
        self.state.transcript.clear()
        self.state.streaming_answer_index = None
        self.stream_buffer.reset()
        self.state.status = messages.READY_STATUS
        self.recover_input()

    def finish_local_command(self) -> None:
        self.state.status = messages.READY_STATUS
        self.recover_input()

    def recover_input(self) -> None:
        self.state.input_enabled = True
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
        visible_delta = self.stream_buffer.append(delta)
        if not visible_delta:
            return
        self._append_visible_stream_delta(visible_delta)

    def _append_visible_stream_delta(self, delta: str) -> None:
        if self.state.streaming_answer_index is None:
            self.state.transcript.append(format_transcript_block("allCode", delta))
            self.state.streaming_answer_index = len(self.state.transcript) - 1
            return
        index = self.state.streaming_answer_index
        if index >= len(self.state.transcript):
            self.state.transcript.append(format_transcript_block("allCode", delta))
            self.state.streaming_answer_index = len(self.state.transcript) - 1
            return
        current = transcript_block_content(self.state.transcript[index])
        self.state.transcript[index] = format_transcript_block("allCode", current + delta)

    def _finalize_answer(self, answer: str) -> None:
        flushed = self.stream_buffer.flush()
        if flushed:
            self._append_visible_stream_delta(flushed)
        final_answer = answer.strip()
        index = self.state.streaming_answer_index
        if index is None or index >= len(self.state.transcript):
            if final_answer:
                self.state.transcript.append(format_transcript_block("allCode", final_answer))
            self.state.streaming_answer_index = None
            return
        if final_answer:
            self.state.transcript[index] = format_transcript_block("allCode", final_answer)
        self.state.streaming_answer_index = None


def format_transcript_block(role: str, content: str) -> str:
    label = TRANSCRIPT_LABELS.get(role, role.strip().upper() or "STATUS")
    body = "\n".join(f"  {line}" if line else "" for line in content.split("\n"))
    return f"{label}\n{body}".rstrip("\n")


def transcript_block_content(block: str) -> str:
    lines = block.strip("\n").splitlines()
    if len(lines) <= 1:
        return ""
    return "\n".join(line[2:] if line.startswith("  ") else line for line in lines[1:])

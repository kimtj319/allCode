"""Convert core agent events into UI-specific events."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from allCode.core.events import AgentEvent
from allCode.core.models import CoreModel
from allCode.tui.renderers import EventRenderer

UIEventKind = Literal[
    "user_prompt_committed",
    "assistant_stream_started",
    "assistant_delta_received",
    "assistant_finalized",
    "tool_status_updated",
    "tool_result_committed",
    "approval_opened",
    "validation_status_updated",
    "turn_failed_visible",
    "footer_status_changed",
]


class UIEvent(CoreModel):
    kind: UIEventKind
    content: str = ""
    status: str = ""
    spinner: bool = False
    role: str = ""
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class TUIEventBridge:
    def __init__(self, renderer: EventRenderer | None = None) -> None:
        self.renderer = renderer or EventRenderer()

    def from_agent_event(self, event: AgentEvent) -> UIEvent:
        rendered = self.renderer.render(event)
        if rendered.transcript_role == "allCode_stream":
            return UIEvent(
                kind="assistant_delta_received",
                content=rendered.transcript,
                status=rendered.status,
                spinner=rendered.spinner,
            )
        if event.event_type == "final_answer_ready":
            return UIEvent(
                kind="assistant_finalized",
                content=rendered.transcript,
                status=rendered.status,
                spinner=False,
            )
        if rendered.transcript_role == "tool" and rendered.transcript:
            return UIEvent(
                kind="tool_result_committed",
                content=rendered.transcript,
                status=rendered.status,
                spinner=rendered.spinner,
                role="tool",
            )
        if rendered.transcript_role == "approval":
            return UIEvent(kind="approval_opened", content=rendered.transcript, status=rendered.status, spinner=rendered.spinner)
        if rendered.transcript_role == "error":
            return UIEvent(kind="turn_failed_visible", content=rendered.transcript, status=rendered.status, role="error")
        if rendered.transcript:
            return UIEvent(
                kind="footer_status_changed" if rendered.transcript_role == "status" else "tool_result_committed",
                content=rendered.transcript,
                status=rendered.status,
                spinner=rendered.spinner,
                role=rendered.transcript_role,
            )
        return UIEvent(kind="footer_status_changed", status=rendered.status, spinner=rendered.spinner)

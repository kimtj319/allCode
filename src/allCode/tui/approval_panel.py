"""Approval panel state for file and shell previews."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from allCode.core.events import ApprovalRequested
from allCode.core.models import CoreModel
from allCode.tui.approval_preview_view import approval_preview_from_payload

ApprovalAction = Literal["approve_once", "deny", "allow_session"]


class ApprovalPanelState(CoreModel):
    visible: bool = False
    reason: str = ""
    preview: str = ""
    risk: str = "low"
    feedback: str = ""
    actions: list[ApprovalAction] = Field(default_factory=lambda: ["approve_once", "deny", "allow_session"])

    @classmethod
    def from_event(cls, event: ApprovalRequested) -> "ApprovalPanelState":
        data = event.data
        view = approval_preview_from_payload(data, fallback_preview=str(data.get("preview", "")))
        return cls(
            visible=True,
            reason=str(data.get("reason", event.message)),
            preview=view.preview,
            risk=str(data.get("risk", "medium")),
        )

    def resolve(self) -> "ApprovalPanelState":
        return self.model_copy(update={"visible": False, "feedback": ""})

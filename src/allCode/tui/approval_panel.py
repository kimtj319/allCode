"""Approval panel state for file and shell previews."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from allCode.core.events import ApprovalRequested
from allCode.core.models import CoreModel

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
        return cls(
            visible=True,
            reason=str(data.get("reason", event.message)),
            preview=str(data.get("preview", "")),
            risk=str(data.get("risk", "medium")),
        )

    def resolve(self) -> "ApprovalPanelState":
        return self.model_copy(update={"visible": False, "feedback": ""})

"""Prompt input model and optional Textual widget."""

from __future__ import annotations

from pydantic import Field

from allCode.core.models import CoreModel

try:
    from textual.widgets import TextArea
except ModuleNotFoundError:
    TextArea = None


class PromptInputState(CoreModel):
    value: str = ""
    enabled: bool = True
    queued: list[str] = Field(default_factory=list)
    placeholder: str = "Ask allCode"

    def submit(self) -> str | None:
        prompt = self.value.strip()
        if not prompt:
            return None
        self.value = ""
        if self.enabled:
            self.enabled = False
            return prompt
        self.queued.append(prompt)
        return None

    def restore(self) -> None:
        self.enabled = True

    def pop_queued(self) -> str | None:
        if not self.queued:
            return None
        self.enabled = False
        return self.queued.pop(0)


if TextArea is not None:

    class PromptInput(TextArea):
        def on_mount(self) -> None:
            self.placeholder = "Ask allCode"

        def set_enabled(self, enabled: bool) -> None:
            self.disabled = not enabled

else:

    class PromptInput:
        def __init__(self) -> None:
            self.state = PromptInputState()

        def set_enabled(self, enabled: bool) -> None:
            self.state.enabled = enabled

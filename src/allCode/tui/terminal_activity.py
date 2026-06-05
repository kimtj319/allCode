"""Activity line rendering for the terminal-native UI."""

from __future__ import annotations

from dataclasses import dataclass

from allCode.tui import messages
from allCode.tui.terminal_frame import StyledLine

SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


@dataclass(frozen=True)
class ActivityProps:
    status: str = ""
    running: bool = False
    elapsed_seconds: int = 0
    spinner_index: int = 0


class TerminalActivityRenderer:
    """Build compact Codex-style activity lines."""

    def render(self, props: ActivityProps) -> list[StyledLine]:
        if not props.running:
            return []
        label = _label_for_status(props.status)
        frame = SPINNER_FRAMES[props.spinner_index % len(SPINNER_FRAMES)]
        return [StyledLine(text=f"{frame} {label} ({props.elapsed_seconds}s · esc to interrupt)", style="dim")]


def _label_for_status(status: str) -> str:
    normalized = status.strip()
    if not normalized or normalized == messages.READY_STATUS:
        return "Working"
    if normalized == messages.MODEL_REQUEST_STATUS:
        return "Sending request"
    if normalized in {messages.MODEL_WAITING_STATUS, messages.SLOW_STREAM_STATUS}:
        return "Waiting for model"
    if normalized == messages.MODEL_CONTINUING_STATUS:
        return "Continuing with tool result"
    if normalized == messages.ANSWERING_STATUS:
        return "Answering"
    if normalized == messages.ORGANIZING_STATUS:
        return "Organizing"
    if normalized == messages.VALIDATION_STATUS:
        return "Validating"
    if normalized == messages.REPAIR_STATUS:
        return "Repairing"
    if normalized == messages.RECOVERY_STATUS:
        return messages.RECOVERY_STATUS
    if normalized == messages.APPROVAL_STATUS:
        return "Waiting for approval"
    if normalized.startswith("도구 실행 중:"):
        return "Running tool:" + normalized.split(":", 1)[1]
    if normalized.startswith("도구 준비 중:"):
        return "Preparing tool:" + normalized.split(":", 1)[1]
    return normalized

"""Activity line rendering for the terminal-native UI."""

from __future__ import annotations

from dataclasses import dataclass

from allCode.tui import messages
from allCode.tui.terminal_frame import StyledLine

# Codex does not cycle spinner glyphs; it shows a steady "•" and breathes the
# brightness of the "• <label>" text through these greyscale levels (captured
# from the real Codex CLI). The suffix "(Ns • esc to interrupt)" stays dim.
_PULSE_LEVELS = (128, 138, 167, 202, 231, 242)
_PULSE = _PULSE_LEVELS + tuple(reversed(_PULSE_LEVELS[1:-1]))  # ping-pong, period 10
_SPINNER = "•"


@dataclass(frozen=True)
class ActivityProps:
    status: str = ""
    running: bool = False
    elapsed_seconds: int = 0
    spinner_index: int = 0
    # Deterministic task-plan checklist lines (header + "✔/▶/☐ step"), shown
    # above the spinner while a multi-step turn runs. Empty for single-step turns.
    plan_lines: tuple[str, ...] = ()


class TerminalActivityRenderer:
    """Build compact Codex-style activity lines with a breathing "•" marker."""

    def render(self, props: ActivityProps) -> list[StyledLine]:
        if not props.running:
            return []
        plan_lines = self._plan_lines(props.plan_lines)
        label = _label_for_status(props.status)
        head = f"{_SPINNER} {label}"
        suffix = f" ({props.elapsed_seconds}s • esc to interrupt)"
        level = _PULSE[props.spinner_index % len(_PULSE)]
        return [
            *plan_lines,
            StyledLine(
                text=head + suffix,
                style="dim",
                fg=(level, level, level),
                bold=True,
                dim_suffix_at=len(head),
            ),
        ]

    @staticmethod
    def _plan_lines(lines: tuple[str, ...]) -> list[StyledLine]:
        rendered: list[StyledLine] = []
        for index, line in enumerate(lines):
            # Header (first line) bold; "✔" steps dim; the active "▶" step plain.
            rendered.append(StyledLine(text=line, style="dim", bold=(index == 0)))
        return rendered


def _label_for_status(status: str) -> str:
    normalized = status.strip()
    if not normalized or normalized == messages.READY_STATUS:
        return "Working"
    if normalized == messages.MODEL_REQUEST_STATUS:
        return "Sending request"
    if normalized == messages.ROUTING_STATUS:
        return "Planning"
    if normalized == messages.WORKFLOW_STATUS:
        return "Executing plan"
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

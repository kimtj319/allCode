"""Pure footer rendering for the terminal composer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from allCode.tui.terminal_frame import StyledLine

FooterMode = Literal[
    "composer_empty",
    "composer_has_draft",
    "task_running",
    "queue_hint",
    "shortcut_overlay",
    "esc_hint",
    "history_search",
]


@dataclass(frozen=True)
class KeyHint:
    key: str
    label: str


@dataclass(frozen=True)
class FooterProps:
    mode: FooterMode
    status_line: str | None = None
    task_running: bool = False
    queued_messages: int = 0
    key_hints: list[KeyHint] = field(default_factory=list)
    active_agent_label: str | None = None


class TerminalFooterRenderer:
    """Format footer props without mutating composer state."""

    def render(self, props: FooterProps, *, width: int) -> list[StyledLine]:
        line = self._line_for_mode(props)
        if line is None:
            line = self._context_line(props)
        if line is None:
            return []
        return [StyledLine(text=self._clip(line, width), style="dim")]

    def _line_for_mode(self, props: FooterProps) -> str | None:
        if props.mode == "task_running":
            if props.queued_messages:
                return f"Tab to queue next prompt · {props.queued_messages} queued · /stop to cancel"
            # The activity line already shows "Working (Ns · esc to interrupt)",
            # so keep the footer for context (model/workspace) like Codex does.
            return None
        if props.mode == "queue_hint":
            return f"{props.queued_messages} queued · Enter to keep editing · /stop to cancel"
        if props.mode == "shortcut_overlay":
            return self._hint_line(props)
        if props.mode == "esc_hint":
            return "Esc again to clear the current draft"
        if props.mode == "history_search":
            return "History search · Enter to accept · Esc to close"
        return None

    def _context_line(self, props: FooterProps) -> str | None:
        parts: list[str] = []
        if props.status_line:
            parts.append(props.status_line)
        if props.active_agent_label:
            parts.append(props.active_agent_label)
        return " · ".join(parts) if parts else None

    def _hint_line(self, props: FooterProps) -> str | None:
        if not props.key_hints:
            return None
        return "  ".join(f"{hint.key} {hint.label}" for hint in props.key_hints)

    @staticmethod
    def _clip(text: str, width: int) -> str:
        if width <= 0:
            return ""
        if len(text) <= width:
            return text
        if width <= 1:
            return text[:width]
        return text[: width - 1] + "…"

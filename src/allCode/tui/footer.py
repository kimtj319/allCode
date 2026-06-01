"""Footer text helpers for the persistent composer."""

from __future__ import annotations


def compose_status_line(
    *,
    status: str,
    spinner_active: bool,
    turn_running: bool,
    queued_count: int,
) -> str:
    """Return the compact status line displayed above the composer."""

    spinner = "⠋ " if spinner_active else ""
    hint = compose_input_hint(turn_running=turn_running, queued_count=queued_count)
    base = f"{spinner}{status}".strip()
    if not hint:
        return base
    if not base:
        return hint
    return f"{base} · {hint}"


def compose_input_hint(*, turn_running: bool, queued_count: int) -> str:
    if turn_running and queued_count:
        return f"{queued_count} queued · Enter to steer · Tab to queue · Esc to interrupt"
    if turn_running:
        return "Enter to steer · Tab to queue · Esc to interrupt"
    if queued_count:
        return f"{queued_count} queued"
    return ""

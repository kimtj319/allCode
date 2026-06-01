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

    if turn_running:
        queued = f" · {queued_count} queued" if queued_count else ""
        spinner = "⠋ " if spinner_active else ""
        return f"{spinner}Working{queued} · esc interrupt · tab queue · enter steer"
    if queued_count:
        return f"{queued_count} queued · enter to run next"
    return status.strip()


def compose_input_hint(*, turn_running: bool, queued_count: int) -> str:
    if turn_running and queued_count:
        return f"{queued_count} queued · esc interrupt · tab queue · enter steer"
    if turn_running:
        return "esc interrupt · tab queue · enter steer"
    if queued_count:
        return f"{queued_count} queued"
    return ""

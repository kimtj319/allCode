"""Interactive UI runtime selection."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO

from allCode.tui.app import TEXTUAL_AVAILABLE, create_app
from allCode.tui.slash_commands import SlashCommandHandler
from allCode.tui.terminal import run_terminal_session

TurnRunner = Any


def run_interactive_session(
    *,
    turn_runner: TurnRunner,
    app_info: str,
    slash_handler: SlashCommandHandler,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    cwd: Path,
    plain_terminal: bool = False,
    textual: bool = False,
    session_id: str | None = None,
) -> int:
    """Run the best available interactive UI.

    The default non-headless UI follows Codex's terminal-native scroll-region
    model. Textual remains available as an explicit optional mode.
    """

    if textual:
        if not TEXTUAL_AVAILABLE:
            stderr.write("Textual is not installed; falling back to the terminal-native UI.\n")
        else:
            app = create_app(turn_runner=turn_runner, app_info=app_info, slash_handler=slash_handler)
            app.run()
            return 0

    return run_terminal_session(
        turn_runner=turn_runner,
        app_info=app_info,
        slash_handler=slash_handler,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
        session_id=session_id,
    )

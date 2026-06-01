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
) -> int:
    """Run the best available interactive UI.

    Textual is the normal non-headless UI. The plain terminal shell remains as a
    fallback for minimal terminals and for explicit compatibility testing.
    """

    if plain_terminal or not TEXTUAL_AVAILABLE:
        if not plain_terminal:
            stderr.write("Textual is not installed; falling back to the plain terminal UI.\n")
        return run_terminal_session(
            turn_runner=turn_runner,
            app_info=app_info,
            slash_handler=slash_handler,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            cwd=cwd,
        )

    app = create_app(turn_runner=turn_runner, app_info=app_info, slash_handler=slash_handler)
    app.run()
    return 0

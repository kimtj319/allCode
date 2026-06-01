from __future__ import annotations

import io
import os

from allCode.tui.slash_commands import SlashCommandHandler
from allCode.tui.terminal import TerminalSession
from allCode.tui.terminal_frame import StyledLine, TerminalFrame
from allCode.tui.terminal_screen import TerminalScreen


class TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_prepare_body_output_clears_composer_and_moves_to_scrollback(monkeypatch) -> None:
    monkeypatch.setattr(
        "allCode.tui.terminal_screen.shutil.get_terminal_size",
        lambda fallback=None: os.terminal_size((80, 24)),
    )
    stream = TTYBuffer()
    screen = TerminalScreen(stdin=stream, stdout=stream)
    screen.set_reserved_rows(4)

    stream.seek(0)
    stream.truncate(0)
    screen.prepare_body_output()

    output = stream.getvalue()
    assert "\x1b[21;1H\x1b[2K" in output
    assert "\x1b[24;1H\x1b[2K" in output
    assert "\x1b[1;20r" in output
    assert output.endswith("\x1b[20;1H\n")


def test_terminal_prompt_print_prepares_body_output_before_rendering(monkeypatch) -> None:
    monkeypatch.setattr(
        "allCode.tui.terminal_screen.shutil.get_terminal_size",
        lambda fallback=None: os.terminal_size((80, 24)),
    )
    stdout = TTYBuffer()
    stderr = TTYBuffer()
    session = TerminalSession(
        turn_runner=lambda prompt, handler: None,
        app_info="model: demo | workspace: repo | approval: ask",
        slash_handler=SlashCommandHandler(),
        stdin=stdout,
        stdout=stdout,
        stderr=stderr,
    )
    calls: list[str] = []
    session.screen.prepare_body_output = lambda: calls.append("body")  # type: ignore[method-assign]

    session._print_user_prompt("테스트 입력입니다")

    assert calls == ["body"]
    assert "테스트 입력입니다" in stdout.getvalue()


def test_terminal_status_print_prepares_body_output_once_for_new_status(monkeypatch) -> None:
    monkeypatch.setattr(
        "allCode.tui.terminal_screen.shutil.get_terminal_size",
        lambda fallback=None: os.terminal_size((80, 24)),
    )
    stdout = TTYBuffer()
    stderr = TTYBuffer()
    session = TerminalSession(
        turn_runner=lambda prompt, handler: None,
        app_info="model: demo | workspace: repo | approval: ask",
        slash_handler=SlashCommandHandler(),
        stdin=stdout,
        stdout=stdout,
        stderr=stderr,
    )
    calls: list[str] = []
    session.screen.prepare_body_output = lambda: calls.append("body")  # type: ignore[method-assign]

    session._print_status("작업 중")
    session._print_status("작업 중")

    assert calls == ["body"]
    assert "작업 중" in stdout.getvalue()


def test_render_bottom_frame_hides_cursor_during_redraw(monkeypatch) -> None:
    monkeypatch.setattr(
        "allCode.tui.terminal_screen.shutil.get_terminal_size",
        lambda fallback=None: os.terminal_size((80, 24)),
    )
    stream = TTYBuffer()
    screen = TerminalScreen(stdin=stream, stdout=stream)

    screen.render_bottom_frame(
        TerminalFrame(
            input_lines=[StyledLine(text="hello")],
            cursor_row=0,
            cursor_col=8,
        )
    )

    output = stream.getvalue()
    assert "\x1b[?25l" in output
    assert "\x1b[?25h" in output
    assert output.index("\x1b[?25l") < output.index("hello") < output.index("\x1b[?25h")

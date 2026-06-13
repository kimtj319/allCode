from __future__ import annotations

import io
import os

from rich.console import Console

from allCode.core.events import FinalAnswerReady, ModelTextDelta
from allCode.tui.slash_commands import SlashCommandHandler
from allCode.tui.terminal import TerminalSession
from allCode.tui.terminal_answer_renderer import TerminalAnswerRenderer
from allCode.tui.terminal_answer_renderer import normalize_terminal_markdown
from allCode.tui.terminal_frame import StyledLine, TerminalFrame
from allCode.tui.terminal_screen import TerminalScreen


class TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_prepare_body_output_clears_composer_and_flows_from_top_when_empty(monkeypatch) -> None:
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
    # Composer rows are cleared and the scroll region is reapplied.
    assert "\x1b[21;1H\x1b[2K" in output
    assert "\x1b[24;1H\x1b[2K" in output
    assert "\x1b[1;20r" in output
    # With no committed body yet, body output flows from the top instead of being
    # pinned to body_bottom (no large gap under the header).
    assert output.endswith("\x1b[1;1H")


def test_prepare_body_output_clamps_to_body_bottom_once_filled(monkeypatch) -> None:
    monkeypatch.setattr(
        "allCode.tui.terminal_screen.shutil.get_terminal_size",
        lambda fallback=None: os.terminal_size((80, 24)),
    )
    stream = TTYBuffer()
    screen = TerminalScreen(stdin=stream, stdout=stream)
    screen.set_reserved_rows(4)
    # Simulate body output that fills past the scroll region (newlines flow
    # through the counting proxy).
    screen.stdout.write("line\n" * 50)

    stream.seek(0)
    stream.truncate(0)
    screen.prepare_body_output()

    output = stream.getvalue()
    # body_bottom for 80x24 with reserved 4 is 20.
    assert output.endswith("\x1b[20;1H")


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


def test_terminal_running_status_updates_bottom_frame_not_body(monkeypatch) -> None:
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
    session._running_started_at = 1.0
    session.screen.prepare_body_output = lambda: (_ for _ in ()).throw(AssertionError("body output should not be used"))

    session._print_status("답변 작성 중")

    output = stdout.getvalue()
    assert "Answering" in output
    assert "esc to interrupt" in output


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


def test_render_bottom_frame_draws_activity_spacer_and_footer(monkeypatch) -> None:
    monkeypatch.setattr(
        "allCode.tui.terminal_screen.shutil.get_terminal_size",
        lambda fallback=None: os.terminal_size((80, 24)),
    )
    stream = TTYBuffer()
    screen = TerminalScreen(stdin=stream, stdout=stream)

    screen.render_bottom_frame(
        TerminalFrame(
            input_lines=[StyledLine(text="")],
            cursor_row=0,
            cursor_col=3,
            activity_lines=[StyledLine(text="⠋ Working (0s · esc to interrupt)", style="dim")],
            spacer_after_activity=True,
            footer_lines=[StyledLine(text="model: demo", style="dim")],
        )
    )

    output = stream.getvalue()
    assert "Working (0s" in output
    assert "model: demo" in output
    assert "\x1b[?25l" in output


def test_terminal_markdown_normalization_removes_html_breaks() -> None:
    normalized = normalize_terminal_markdown("**제목**<br>다음 줄")

    assert "<br>" not in normalized
    assert "**제목**" in normalized
    assert "다음 줄" in normalized


def test_terminal_markdown_normalization_compacts_provider_citations() -> None:
    citation = "\u30101\u2020title\u3011"
    title_citation = "\u3010Download Python | Python.org\u3011"
    normalized = normalize_terminal_markdown(f"Python 최신 버전은 3.14.0입니다{citation}. 근거: {title_citation}")

    assert "【" not in normalized
    assert "†title" not in normalized
    assert "3.14.0입니다[1]." in normalized
    assert "근거: [Download Python | Python.org]" in normalized


def test_terminal_markdown_renderer_compacts_code_blocks() -> None:
    output = _render_answer("```python\nprint('ok')\n```")

    assert "print('ok')" in output
    assert not output.startswith("\n")
    assert "\n\nprint('ok')" not in output


def test_terminal_markdown_renderer_uses_distinct_quote_marker() -> None:
    output = _render_answer("> quoted line")

    assert "│ quoted line" in output
    assert "▌ quoted line" not in output


def test_terminal_markdown_renderer_compacts_pipe_tables() -> None:
    output = _render_answer("| 기능 | 상태 |\n| --- | --- |\n| 렌더링 | 정상 |")

    assert "기능" in output
    assert "렌더링" in output
    assert "---" not in output
    assert not output.startswith("\n")


def test_terminal_markdown_renderer_falls_back_for_narrow_tables() -> None:
    output = _render_answer(
        "| very long header | another long header |\n"
        "| --- | --- |\n"
        "| very long cell value | another long cell value |",
        width=24,
    )

    assert "•" in output
    assert "very long header:" in output
    assert "---" not in output


def test_terminal_markdown_renderer_falls_back_for_malformed_pipe_tables() -> None:
    output = _render_answer(
        "| 구분 | 내용 |\n"
        "| --- | --- |\n"
        "| 핵심 컴포넌트 | - FreeType 라이브러리 업데이트\n"
        "• Libpng 업데이트 | | 성능/버그 수정 | - GZIPInputStream 회귀 수정\n"
        "• VM 초기화 안정성 향상 |",
        width=100,
    )

    assert "구분 / 내용" in output
    assert "핵심 컴포넌트: FreeType 라이브러리 업데이트" in output
    assert "성능/버그 수정: GZIPInputStream 회귀 수정" in output
    assert "| |" not in output
    assert "| 핵심" not in output
    assert "• •" not in output
    assert "• Libpng 업데이트" in output
    assert "• VM 초기화 안정성 향상" in output
    assert "· -" not in output
    assert "---" not in output


def test_terminal_markdown_renderer_left_aligns_headings() -> None:
    output = _render_answer("# 제목")

    assert "제목" in output
    # Heading is left-aligned (not centered/underlined); it follows the Codex-style
    # turn marker rather than being padded to the center.
    assert output.lstrip().startswith("• 제목")
    assert "═" not in output


def test_terminal_session_restores_idle_composer_after_turn(monkeypatch) -> None:
    monkeypatch.setattr(
        "allCode.tui.terminal_screen.shutil.get_terminal_size",
        lambda fallback=None: os.terminal_size((80, 24)),
    )

    async def runner(prompt, event_handler):
        await event_handler(FinalAnswerReady(turn_id="t1", message="ready", final_answer="완료되었습니다."))

    stdout = TTYBuffer()
    stderr = TTYBuffer()
    session = TerminalSession(
        turn_runner=runner,
        app_info="model: demo | workspace: repo | approval: ask",
        slash_handler=SlashCommandHandler(),
        stdin=stdout,
        stdout=stdout,
        stderr=stderr,
    )
    frames: list[str | None] = []
    clears: list[str] = []
    session.input_editor.render_runtime_frame = lambda *, activity=None: frames.append(  # type: ignore[method-assign]
        activity.status if activity is not None else None
    )
    session.screen.clear_input_panel = lambda: clears.append("clear")  # type: ignore[method-assign]

    session._run_agent_prompt("테스트")

    assert "완료되었습니다." in stdout.getvalue()
    assert frames[0] is not None
    assert frames[-1] is None
    assert clears
    assert session._running_started_at is None


def test_terminal_session_stops_answering_activity_when_final_answer_arrives(monkeypatch) -> None:
    monkeypatch.setattr(
        "allCode.tui.terminal_screen.shutil.get_terminal_size",
        lambda fallback=None: os.terminal_size((80, 24)),
    )

    frames: list[str | None] = []
    frames_after_final_event: list[str | None] = []

    async def runner(prompt, event_handler):
        await event_handler(FinalAnswerReady(turn_id="t1", message="ready", final_answer="완료되었습니다."))
        frames_after_final_event.extend(frames)

    stdout = TTYBuffer()
    stderr = TTYBuffer()
    session = TerminalSession(
        turn_runner=runner,
        app_info="model: demo | workspace: repo | approval: ask",
        slash_handler=SlashCommandHandler(),
        stdin=stdout,
        stdout=stdout,
        stderr=stderr,
    )
    session.input_editor.render_runtime_frame = lambda *, activity=None: frames.append(  # type: ignore[method-assign]
        activity.status if activity is not None else None
    )

    session._run_agent_prompt("테스트")

    assert "완료되었습니다." in stdout.getvalue()
    assert frames_after_final_event[-1] is None
    assert frames[-1] is None
    assert frames.count(None) == 1
    assert session._running_started_at is None


def test_terminal_session_holds_numbered_markdown_heading_until_complete(monkeypatch) -> None:
    monkeypatch.setattr(
        "allCode.tui.terminal_screen.shutil.get_terminal_size",
        lambda fallback=None: os.terminal_size((80, 24)),
    )

    async def runner(prompt, event_handler):
        await event_handler(ModelTextDelta(turn_id="t1", message="**1.", delta="**1."))
        await event_handler(ModelTextDelta(turn_id="t1", message=" 최신 Java 버전**\n", delta=" 최신 Java 버전**\n"))
        await event_handler(FinalAnswerReady(turn_id="t1", message="ready", final_answer=""))

    stdout = TTYBuffer()
    stderr = TTYBuffer()
    session = TerminalSession(
        turn_runner=runner,
        app_info="model: demo | workspace: repo | approval: ask",
        slash_handler=SlashCommandHandler(),
        stdin=stdout,
        stdout=stdout,
        stderr=stderr,
    )

    session._run_agent_prompt("stream heading")

    output = stdout.getvalue()
    assert "**1." not in output
    assert "최신 Java 버전" in output


def test_terminal_tool_rows_do_not_add_blank_lines_between_observations() -> None:
    from io import StringIO

    from allCode.core.events import ToolExecutionFinished, TurnFinalized
    from allCode.core.models import ToolResult

    async def runner(prompt, event_handler):
        await event_handler(
            ToolExecutionFinished(
                turn_id="t1",
                message="search done",
                result=ToolResult(
                    call_id="c1",
                    name="web_search",
                    ok=True,
                    content="raw search payload",
                    metadata={"query": "java", "observation": {"summary": "Collected 5 web evidence item(s)"}},
                ),
            )
        )
        await event_handler(
            ToolExecutionFinished(
                turn_id="t1",
                message="fetch done",
                result=ToolResult(
                    call_id="c2",
                    name="web_fetch",
                    ok=True,
                    content="raw page payload",
                    metadata={"url": "https://example.test", "observation": {"summary": "Collected 1 page"}},
                ),
            )
        )
        await event_handler(TurnFinalized(turn_id="t1", message="done", status="success", final_answer="완료"))

    stdout = StringIO()
    session = TerminalSession(
        turn_runner=runner,
        app_info="model: demo | workspace: repo | approval: ask",
        slash_handler=SlashCommandHandler(),
        stdin=StringIO("hello\n/exit\n"),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert session.run() == 0

    output = stdout.getvalue()
    first = "• web_search java -> ok · Collected 5 web evidence item(s)"
    second = "• web_fetch -> ok · Collected 1 page"
    assert first in output
    assert second in output
    between = output.split(first, 1)[1].split(second, 1)[0]
    assert "\n\n" not in between


def _render_answer(markdown: str, *, width: int = 80) -> str:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, width=width, highlight=False)
    TerminalAnswerRenderer(console).render(markdown)
    return stream.getvalue()

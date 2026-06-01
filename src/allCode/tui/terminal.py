"""Terminal-first interactive shell for allCode."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, TextIO

from rich.console import Console
from rich.markdown import Markdown

from allCode.core.events import AgentEvent
from allCode.tui.markdown import logo_text
from allCode.tui.renderers import EventRenderer
from allCode.tui.slash_commands import SlashCommandHandler
from allCode.tui.terminal_input import TerminalInputEditor
from allCode.tui.terminal_markdown import MarkdownStreamPrinter
from allCode.tui.terminal_screen import TerminalScreen, TerminalTheme

TurnRunner = Any


class TerminalSession:
    """Codex-style terminal session using normal terminal scrollback."""

    def __init__(
        self,
        *,
        turn_runner: TurnRunner,
        app_info: str,
        slash_handler: SlashCommandHandler,
        stdin: TextIO,
        stdout: TextIO,
        stderr: TextIO,
        theme: TerminalTheme | None = None,
        cwd: Path | None = None,
    ) -> None:
        self.turn_runner = turn_runner
        self.app_info = app_info
        self.slash_handler = slash_handler
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.screen = TerminalScreen(stdin=stdin, stdout=stdout, theme=theme or TerminalTheme())
        self.input_editor = TerminalInputEditor(
            screen=self.screen,
            stdin=stdin,
            stdout=stdout,
            registry=slash_handler.registry,
            cwd=cwd or Path.cwd(),
            footer=app_info.replace(" | ", " · "),
        )
        self.console = Console(
            file=stdout,
            force_terminal=self.screen.interactive,
            color_system="truecolor" if self.screen.interactive else None,
            highlight=False,
        )
        self.error_console = Console(
            file=stderr,
            force_terminal=self.screen.interactive and self._is_terminal(stderr),
            color_system="truecolor" if self.screen.interactive and self._is_terminal(stderr) else None,
            highlight=False,
        )
        self.renderer = EventRenderer()
        self._last_status = ""
        self._stream_started = False
        self._stream_printer = MarkdownStreamPrinter(stdout, enabled=self.screen.interactive)

    def run(self) -> int:
        self.screen.enter()
        try:
            self._print_header()
            while True:
                try:
                    prompt = self.input_editor.read_prompt()
                except EOFError:
                    self.stdout.write("\n")
                    return 0
                except KeyboardInterrupt:
                    self.stderr.write("\nInterrupted.\n")
                    return 130
                if not prompt.strip():
                    continue
                normalized_prompt = prompt.strip()
                if normalized_prompt.startswith("/"):
                    exit_code = self._run_slash_command(normalized_prompt)
                    if exit_code is not None:
                        return exit_code
                    continue
                self._run_agent_prompt(prompt)
        finally:
            self.screen.exit()

    async def handle_agent_event(self, event: AgentEvent) -> None:
        rendered = self.renderer.render(event)
        if rendered.transcript_role == "allCode_stream":
            if rendered.status:
                self._print_status(rendered.status)
            self._start_stream()
            self._stream_printer.write(rendered.transcript)
            return
        if event.event_type == "final_answer_ready":
            final_answer = getattr(event, "final_answer", event.message)
            if self._stream_started:
                self._stream_printer.finish()
            elif final_answer.strip():
                self._print_assistant_block(final_answer)
            self._last_status = ""
            return
        if rendered.transcript and rendered.severity == "user_visible":
            self._print_rendered_block(rendered.transcript_role, rendered.transcript)
        elif rendered.status and rendered.severity != "debug_only":
            self._print_status(rendered.status)

    def _run_agent_prompt(self, prompt: str) -> None:
        self._print_user_prompt(prompt)
        self._stream_started = False
        self._stream_printer.reset()
        self._last_status = ""
        try:
            asyncio.run(self.turn_runner(prompt, self.handle_agent_event))
        except KeyboardInterrupt:
            self.stderr.write("\nInterrupted.\n")
        except Exception as exc:
            self.error_console.print(f"[bold red]오류:[/] {exc}")
        finally:
            if self._stream_started:
                self._stream_printer.finish()
            self.stdout.write("\n")
            self.stdout.flush()

    def _run_slash_command(self, command: str) -> int | None:
        self._print_user_prompt(command)
        result = asyncio.run(self.slash_handler.handle(command))
        if result.clear_transcript:
            self._clear_screen()
        if result.message:
            self._print_assistant_block(result.message)
        if result.exit_requested:
            return 0
        return None

    def _print_header(self) -> None:
        self.console.print(logo_text(self.app_info))
        self.console.print()

    def _print_user_prompt(self, prompt: str) -> None:
        self._prepare_body_output()
        self.console.print(f"[dim]▌[/] {prompt}")
        self.console.print("[dim]" + "─" * min(74, max(20, self.console.width - 4)) + "[/]")

    def _print_assistant_block(self, text: str) -> None:
        self._prepare_body_output()
        self.console.print("[bold]allCode[/]")
        if text.strip():
            self.console.print(Markdown(text))
        self.console.print()

    def _print_rendered_block(self, role: str, text: str) -> None:
        if role == "error":
            self._prepare_body_output()
            self.error_console.print(f"[bold red]오류:[/] {text}")
            return
        if role == "tool":
            self._prepare_body_output()
            self.console.print("[dim]tool[/]")
            self.console.print(Markdown(f"```text\n{text}\n```"))
            return
        self._print_assistant_block(text)

    def _print_status(self, status: str) -> None:
        if not status or status == self._last_status:
            return
        self._prepare_body_output()
        self.console.print(f"[dim]· {status}[/]")
        self._last_status = status

    def _start_stream(self) -> None:
        if self._stream_started:
            return
        self._prepare_body_output()
        self.console.print("[bold]allCode[/]")
        self._stream_started = True

    def _clear_screen(self) -> None:
        self.screen.clear_all()

    def _prepare_body_output(self) -> None:
        self.screen.prepare_body_output()

    @staticmethod
    def _is_terminal(stream: TextIO) -> bool:
        isatty = getattr(stream, "isatty", None)
        return bool(isatty and isatty())

def run_terminal_session(
    *,
    turn_runner: TurnRunner,
    app_info: str,
    slash_handler: SlashCommandHandler,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    cwd: Path | None = None,
) -> int:
    return TerminalSession(
        turn_runner=turn_runner,
        app_info=app_info,
        slash_handler=slash_handler,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
    ).run()

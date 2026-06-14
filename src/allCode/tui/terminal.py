"""Terminal-first interactive shell for allCode."""

from __future__ import annotations

import asyncio
import inspect
import time
from pathlib import Path
from typing import Any, TextIO

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from allCode.core.events import AgentEvent
from allCode.tui import messages
from allCode.tui.approval_preview_view import approval_preview_from_payload
from allCode.tui.markdown import logo_text
from allCode.tui.renderers import EventRenderer
from allCode.tui.slash_commands import SlashCommandHandler
from allCode.tui.streaming import MarkdownStreamBuffer
from allCode.tui.terminal_activity import ActivityProps
from allCode.tui.terminal_answer_renderer import TerminalAnswerRenderer
from allCode.tui.terminal_input import TerminalInputEditor
from allCode.tui.terminal_screen import TerminalScreen, TerminalTheme
from allCode.tools.approval import ApprovalAction, ApprovalRequest

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
            file=self.screen.stdout,
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
        self._stream_buffer = ""
        self._stream_markdown_buffer = MarkdownStreamBuffer()
        self._final_answer_rendered = False
        self._running_started_at: float | None = None
        self._spinner_index = 0
        self._composer_render_at = 0.0
        self._composer_status: str | None = None
        self.answer_renderer = TerminalAnswerRenderer(self.console)
        self._turn_runner_accepts_approval = self._accepts_approval_handler(turn_runner)

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
        if event.event_type == "approval_requested":
            self._print_status(messages.APPROVAL_STATUS)
            return
        rendered = self.renderer.render(event)
        if rendered.transcript_role == "allCode_stream":
            if rendered.status:
                self._print_status(rendered.status)
            self._stream_started = True
            self._stream_buffer += rendered.transcript
            visible_chunk = self._stream_markdown_buffer.append(rendered.transcript)
            if visible_chunk.strip():
                self._print_assistant_stream_chunk(visible_chunk)
                self._final_answer_rendered = True
            self._render_running_composer(rendered.status or messages.ANSWERING_STATUS)
            return
        if event.event_type in {"final_answer_ready", "turn_finalized"}:
            final_answer = getattr(event, "final_answer", event.message)
            pending_stream = self._stream_markdown_buffer.flush()
            if pending_stream.strip():
                self._print_assistant_stream_chunk(pending_stream)
                self._final_answer_rendered = True
            answer = final_answer if final_answer.strip() else self._stream_buffer
            if answer.strip() and not self._final_answer_rendered:
                self._print_assistant_block(answer)
                self._final_answer_rendered = True
            self._last_status = ""
            self._finish_running_composer()
            return
        if rendered.transcript and rendered.severity == "user_visible":
            self._print_rendered_block(rendered.transcript_role, rendered.transcript)
            if rendered.diff:
                self._print_diff(rendered.diff)
        elif rendered.status and rendered.severity != "debug_only":
            self._print_status(rendered.status)

    def _run_agent_prompt(self, prompt: str) -> None:
        self._print_user_prompt(prompt)
        self._stream_started = False
        self._stream_buffer = ""
        self._stream_markdown_buffer.reset()
        self.answer_renderer.reset()
        self._final_answer_rendered = False
        self._last_status = ""
        self._running_started_at = time.monotonic()
        self._render_running_composer(messages.MODEL_REQUEST_STATUS)
        try:
            asyncio.run(self._run_turn(prompt))
        except KeyboardInterrupt:
            self.stderr.write("\nInterrupted.\n")
        except Exception as exc:
            self.error_console.print(f"[bold red]오류:[/] {exc}")
        finally:
            self._finish_running_composer()

    async def _run_turn(self, prompt: str) -> None:
        if self._turn_runner_accepts_approval:
            await self.turn_runner(prompt, self.handle_agent_event, self.handle_approval_request)
            return
        await self.turn_runner(prompt, self.handle_agent_event)

    async def handle_approval_request(self, request: ApprovalRequest) -> ApprovalAction:
        self._prepare_body_output()
        self.console.print(f"[bold]{messages.APPROVAL_REQUIRED_TITLE}[/]")
        self.console.print(f"[dim]{request.tool_name} · risk: {request.risk}[/]")
        view = approval_preview_from_payload(request.decision.model_dump(mode="json"), fallback_preview="")
        if view.summary:
            self.console.print(f"[dim]{view.summary}[/]")
        preview = view.preview
        if not preview:
            preview = self._approval_preview(request.preview)
        if preview:
            language = "bash" if view.kind == "shell_command" else "diff"
            self.console.print(Markdown(f"```{language}\n{preview}\n```"))
        self.stdout.write(messages.APPROVAL_ACTION_PROMPT)
        self.stdout.flush()
        line = self.stdin.readline()
        choice = (line or "").strip().lower()
        if choice in {"y", "yes"}:
            action: ApprovalAction = "approve_once"
        elif choice in {"a", "allow"}:
            action = "allow_session"
        else:
            action = "deny"
        self.stdout.write("\n")
        self.stdout.flush()
        self._render_running_composer(messages.WORKING_STATUS)
        return action

    def _run_slash_command(self, command: str) -> int | None:
        self._print_user_prompt(command)
        result = asyncio.run(self.slash_handler.handle(command))
        if result.clear_transcript:
            self._clear_screen()
        if result.message:
            self.answer_renderer.reset()
            self._print_assistant_block(result.message)
        if result.exit_requested:
            return 0
        if result.submit_prompt:
            # A custom command expands to a prompt that runs as a normal turn.
            self._run_agent_prompt(result.submit_prompt)
        return None

    def _print_header(self) -> None:
        self.console.print(logo_text(self.app_info))
        self.console.print()

    def _print_user_prompt(self, prompt: str) -> None:
        self._prepare_body_output()
        # One blank line separates turns; Codex shows the submitted prompt with a
        # dim "›" marker rather than fencing it with a full-width rule.
        self.console.print()
        self.console.print(f"[dim]›[/] [dim]{prompt}[/]")

    def _print_assistant_block(self, text: str) -> None:
        self._prepare_body_output()
        self.answer_renderer.render(text)
        self.console.print()

    def _print_assistant_stream_chunk(self, text: str) -> None:
        self._prepare_body_output()
        self.answer_renderer.render(text)

    def _print_rendered_block(self, role: str, text: str) -> None:
        if role == "error":
            self._prepare_body_output()
            self.error_console.print(f"[bold red]오류:[/] {text}")
            return
        if role == "tool":
            self._prepare_body_output()
            self.console.print(f"[dim]{text}[/]")
            self._render_running_composer()
            return
        self._print_assistant_block(text)

    def _print_diff(self, diff: str, *, max_lines: int = 80) -> None:
        # Render a file edit as a colored unified diff (Codex-style): green for
        # additions, red for removals, dim cyan for hunk headers. Indented two
        # columns so it reads as detail under the "• tool" summary row.
        if not diff.strip():
            return
        self._prepare_body_output()
        lines = diff.splitlines()
        for raw in lines[:max_lines]:
            text = Text("  ")
            if raw.startswith("@@"):
                text.append(raw, style="cyan")
            elif raw.startswith("+"):
                text.append(raw, style="green")
            elif raw.startswith("-"):
                text.append(raw, style="red")
            else:
                text.append(raw, style="dim")
            self.console.print(text)
        if len(lines) > max_lines:
            self.console.print(Text(f"  ... {len(lines) - max_lines} more diff lines ...", style="dim"))
        self._render_running_composer()

    def _print_status(self, status: str) -> None:
        if not status:
            return
        if self._running_started_at is not None:
            self._render_running_composer(status)
            self._last_status = status
            return
        if status == self._last_status:
            return
        self._prepare_body_output()
        self.console.print(f"[dim]· {status}[/]")
        self._last_status = status

    def _clear_screen(self) -> None:
        self.screen.clear_all()

    def _prepare_body_output(self) -> None:
        self.screen.prepare_body_output()

    def _render_running_composer(self, status: str | None = None) -> None:
        if self._running_started_at is None:
            return
        now = time.monotonic()
        effective_status = status or self._last_status or messages.WORKING_STATUS
        # Throttle spinner-only repaints to ~30fps. During streaming this method
        # is invoked per model-text delta (often many per second); repainting the
        # whole composer pane each time floods the terminal with redundant
        # erase/redraw sequences. A status change always repaints immediately so
        # phase transitions stay responsive.
        if effective_status == self._composer_status and (now - self._composer_render_at) < 0.033:
            return
        self._spinner_index += 1
        self._composer_render_at = now
        self._composer_status = effective_status
        elapsed = max(0, int(now - self._running_started_at))
        self.input_editor.render_runtime_frame(
            activity=ActivityProps(
                status=effective_status,
                running=True,
                elapsed_seconds=elapsed,
                spinner_index=self._spinner_index,
            )
        )

    def _finish_running_composer(self) -> None:
        if self._running_started_at is None:
            return
        self._running_started_at = None
        if self.screen.interactive:
            self.screen.clear_input_panel()
            self.input_editor.render_runtime_frame(activity=None)
        else:
            self.stdout.write("\n")
        self.stdout.flush()

    @staticmethod
    def _is_terminal(stream: TextIO) -> bool:
        isatty = getattr(stream, "isatty", None)
        return bool(isatty and isatty())

    @staticmethod
    def _accepts_approval_handler(turn_runner: TurnRunner) -> bool:
        try:
            signature = inspect.signature(turn_runner)
        except (TypeError, ValueError):
            return True
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind in {parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD}
        ]
        if any(parameter.kind == parameter.VAR_POSITIONAL for parameter in signature.parameters.values()):
            return True
        return len(positional) >= 3 or "approval_handler" in signature.parameters

    @staticmethod
    def _approval_preview(preview: str, *, max_lines: int = 120, max_chars: int = 8000) -> str:
        if not preview:
            return ""
        lines = preview.splitlines()
        clipped = "\n".join(lines[:max_lines])
        if len(lines) > max_lines:
            clipped += "\n... diff truncated ..."
        if len(clipped) > max_chars:
            clipped = clipped[:max_chars].rstrip() + "\n... diff truncated ..."
        return clipped

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

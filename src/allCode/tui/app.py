"""Textual application shell for allCode."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from allCode.core.events import AgentEvent, TurnFailed
from allCode.tui.command_palette import CommandPalette, CommandPaletteState
from allCode.tui.layout import TUIStateController
from allCode.tui.markdown import logo_text, transcript_to_markdown
from allCode.tui.slash_commands import SlashCommandHandler
from allCode.tui.styles import APP_CSS

try:
    from textual.app import App, ComposeResult
    from textual.containers import Vertical
    from textual.widgets import Input, Markdown, Static

    TEXTUAL_AVAILABLE = True
except ModuleNotFoundError:
    App = object
    ComposeResult = Any
    Vertical = None
    Input = None
    Markdown = None
    Static = None
    TEXTUAL_AVAILABLE = False

TurnRunner = Callable[[str, Callable[[AgentEvent], Awaitable[None]]], Awaitable[None]]


async def noop_turn_runner(prompt: str, event_handler: Callable[[AgentEvent], Awaitable[None]]) -> None:
    await event_handler(
        TurnFailed(
            turn_id="tui",
            message="No turn runner is configured.",
            error_type="TUI_NO_RUNNER",
        )
    )


if TEXTUAL_AVAILABLE:

    class AllCodeApp(App):
        CSS = APP_CSS
        BINDINGS = [("escape", "cancel_active", "Cancel"), ("ctrl+c", "cancel_active", "Cancel")]

        def __init__(
            self,
            *,
            turn_runner: TurnRunner | None = None,
            app_info: str = "",
            slash_handler: SlashCommandHandler | None = None,
        ) -> None:
            super().__init__()
            self.controller = TUIStateController()
            self.turn_runner = turn_runner or noop_turn_runner
            self.app_info = app_info
            self.slash_handler = slash_handler or SlashCommandHandler()
            self.command_palette = CommandPalette(self.slash_handler.registry)
            self.command_palette_state = CommandPaletteState()
            self._turn_running = False
            self.exit_requested = False

        def compose(self) -> ComposeResult:
            with Vertical(id="app_frame"):
                yield Static(logo_text(self.app_info), id="hero")
                with Vertical(id="transcript_container"):
                    yield Markdown("", id="transcript")
                yield Static(self.controller.state.status, id="status")
                yield Static("", id="command_palette")
                yield Input(placeholder="› Ask allCode", id="input")

        def on_mount(self) -> None:
            self.query_one("#input", Input).focus()

        async def on_input_submitted(self, event: Input.Submitted) -> None:
            prompt = event.value.strip()
            if not prompt:
                return
            event.input.value = ""
            self.command_palette_state.update("", self.command_palette)
            self._refresh_command_palette()
            if prompt.startswith("/"):
                await self.submit_slash_command(prompt)
                return
            await self.submit_prompt(prompt)

        def on_input_changed(self, event: Input.Changed) -> None:
            self.command_palette_state.update(event.value, self.command_palette)
            self._refresh_command_palette()

        async def submit_prompt(self, prompt: str) -> None:
            if self._turn_running:
                self.controller.queue_prompt(prompt)
                self._refresh_widgets()
                return
            self.controller.submit_prompt(prompt)
            self._turn_running = True
            widgets_ready = self._refresh_widgets()
            if widgets_ready:
                self.run_worker(self._run_turn(prompt), exclusive=False, group="agent_run")
            else:
                await self._run_turn(prompt)

        async def submit_slash_command(self, command: str) -> None:
            self.controller.submit_prompt(command)
            self._refresh_widgets()
            result = await self.slash_handler.handle(command)
            if result.cancel_active or result.exit_requested:
                self.workers.cancel_group(self, "agent_run")
                self._turn_running = False
                self.controller.clear_queued_inputs()
            if result.clear_transcript:
                self.controller.clear_transcript()
            elif result.message:
                self.controller.append_message("allCode", result.message)
                self.controller.finish_local_command()
            else:
                self.controller.finish_local_command()
            widgets_ready = self._refresh_widgets()
            if result.exit_requested:
                self.exit_requested = True
                if widgets_ready:
                    self.exit()

        async def _run_turn(self, prompt: str) -> None:
            cancelled = False
            try:
                await self.turn_runner(prompt, self.handle_agent_event)
            except asyncio.CancelledError:
                cancelled = True
                self.controller.recover_input()
                self._refresh_widgets()
                raise
            except Exception as exc:
                await self.handle_agent_event(
                    TurnFailed(turn_id="tui", message=str(exc), error_type="TUI_WORKER_CRASH")
                )
            finally:
                self._turn_running = False
                self.controller.recover_input()
                self._refresh_widgets()
                if not cancelled:
                    await self._run_next_queued_prompt()

        async def handle_agent_event(self, event: AgentEvent) -> None:
            if self._in_app_thread():
                self.controller.handle_event(event)
                self._refresh_widgets()
                return
            self.call_from_thread(self.controller.handle_event, event)
            self.call_from_thread(self._refresh_widgets)

        def action_cancel_active(self) -> None:
            self.workers.cancel_group(self, "agent_run")
            self.controller.clear_queued_inputs()
            self.controller.recover_input()
            self._refresh_widgets()

        def _refresh_widgets(self) -> bool:
            try:
                transcript = self.query_one("#transcript", Markdown)
                status = self.query_one("#status", Static)
                input_box = self.query_one("#input", Input)
            except Exception:
                return False
            transcript.update(transcript_to_markdown(self.controller.state.transcript))
            spinner = "⠋ " if self.controller.state.spinner_active else ""
            status.update(spinner + self.controller.state.status)
            input_box.disabled = not self.controller.state.input_enabled
            if self.controller.state.input_enabled:
                input_box.focus()
            self._refresh_command_palette()
            return True

        def _refresh_command_palette(self) -> None:
            try:
                palette_box = self.query_one("#command_palette", Static)
            except Exception:
                return
            if not self.command_palette_state.visible:
                palette_box.update("")
                palette_box.styles.height = 0
                return
            rows = [f"{command.name}  {command.description}" for command in self.command_palette_state.matches[:4]]
            palette_box.update("\n".join(rows) if rows else "일치하는 명령어가 없습니다.")
            palette_box.styles.height = max(1, len(rows))

        async def _run_next_queued_prompt(self) -> None:
            if self._turn_running:
                return
            prompt = self.controller.next_queued_input()
            if prompt is not None:
                await self.submit_prompt(prompt)

        def _in_app_thread(self) -> bool:
            return getattr(self, "_thread_id", None) == threading.get_ident()

else:

    class AllCodeApp:
        def __init__(
            self,
            *,
            turn_runner: TurnRunner | None = None,
            app_info: str = "",
            slash_handler: SlashCommandHandler | None = None,
        ) -> None:
            self.controller = TUIStateController()
            self.turn_runner = turn_runner or noop_turn_runner
            self.app_info = app_info
            self.slash_handler = slash_handler or SlashCommandHandler()
            self.exit_requested = False

        async def submit_prompt(self, prompt: str) -> None:
            self.controller.submit_prompt(prompt)
            try:
                await self.turn_runner(prompt, self.handle_agent_event)
            except asyncio.CancelledError:
                self.controller.recover_input()
                raise
            except Exception as exc:
                await self.handle_agent_event(TurnFailed(turn_id="tui", message=str(exc), error_type="TUI_WORKER_CRASH"))

        async def handle_agent_event(self, event: AgentEvent) -> None:
            self.controller.handle_event(event)

        async def submit_slash_command(self, command: str) -> None:
            self.controller.submit_prompt(command)
            result = await self.slash_handler.handle(command)
            if result.cancel_active or result.exit_requested:
                self.controller.clear_queued_inputs()
            if result.clear_transcript:
                self.controller.clear_transcript()
            elif result.message:
                self.controller.append_message("allCode", result.message)
                self.controller.finish_local_command()
            else:
                self.controller.finish_local_command()
            if result.exit_requested:
                self.exit_requested = True

        def run(self) -> None:
            raise RuntimeError("Textual is not installed; use headless mode or install the project dependencies.")


def create_app(
    *,
    turn_runner: TurnRunner | None = None,
    app_info: str = "",
    slash_handler: SlashCommandHandler | None = None,
) -> AllCodeApp:
    return AllCodeApp(turn_runner=turn_runner, app_info=app_info, slash_handler=slash_handler)

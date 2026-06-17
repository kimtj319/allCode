"""Terminal-first interactive shell for allCode."""

from __future__ import annotations

import asyncio
import inspect
import select
import threading
import time
from pathlib import Path
from typing import Any, TextIO

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from allCode.core.events import AgentEvent
from allCode.tui import messages
from allCode.tui.approval_preview_view import approval_preview_from_payload
from allCode.memory.usage_store import UsageStore
from allCode.tui.markdown import logo_text
from allCode.tui.mentions import expand_mentions
from allCode.tui.status_view import (
    DAILY_TOKEN_BUDGET,
    columns_for_width,
    fmt_tokens,
    gauge_fraction,
)
from allCode.tui.renderers import EventRenderer
from allCode.tui.slash_commands import SlashCommandHandler
from allCode.tui.streaming import MarkdownStreamBuffer
from allCode.llm.response_parser import sanitize_channel_markup
from allCode.tui.terminal_activity import ActivityProps
from allCode.tui.terminal_answer_renderer import TerminalAnswerRenderer
from allCode.tui.terminal_input import TerminalInputEditor
from allCode.tui.terminal_screen import TerminalScreen, TerminalTheme
from allCode.tools.approval import ApprovalAction, ApprovalRequest

TurnRunner = Any


class _SteeringCapture:
    """Capture full lines typed while a turn runs and queue them as steering.

    During a turn the TTY is in cooked (line) mode, so a background thread can
    ``select`` + ``readline`` to grab Enter-terminated lines without disturbing
    the streaming output. It is paused around interactive approval prompts so it
    never steals an approval response, and stops promptly when the turn ends."""

    def __init__(self, stdin: TextIO, steering) -> None:
        self._stdin = stdin
        self._steering = steering
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._steering is None:
            return
        try:
            if not self._stdin.isatty():
                return
            self._stdin.fileno()
        except (OSError, ValueError, AttributeError):
            return
        self._thread = threading.Thread(target=self._loop, name="steering-capture", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.3)
            self._thread = None

    def _loop(self) -> None:
        try:
            fd = self._stdin.fileno()
        except (OSError, ValueError):
            return
        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(0.05)
                continue
            try:
                ready, _, _ = select.select([fd], [], [], 0.15)
            except (OSError, ValueError):
                return
            # Re-check after the select wait: an approval prompt may have paused
            # us while we were blocked, in which case the pending bytes belong to
            # the approval reader, not to steering.
            if not ready or self._paused.is_set() or self._stop.is_set():
                continue
            try:
                line = self._stdin.readline()
            except (OSError, ValueError):
                return
            if not line:
                return
            self._steering.push(line.strip())


class TerminalSession:
    """Codex-style terminal session using normal terminal scrollback."""

    # Ring the terminal bell only after a turn this long (seconds), so quick
    # answers don't beep but a long build/generation gets your attention.
    _NOTIFY_AFTER_SECONDS = 10.0

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
        session_id: str | None = None,
    ) -> None:
        self.turn_runner = turn_runner
        self.app_info = app_info
        self.slash_handler = slash_handler
        self._cwd = cwd or Path.cwd()
        # Used to print a resume hint on exit once the session has real history.
        self._session_id = session_id
        self._had_turn = False
        # Per-day token tally for the /status usage gauge (survives across launches).
        self._usage = UsageStore(self._cwd)
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
        # Persistent context/session meta shown in the always-redrawn footer.
        self._base_footer = app_info.replace(" | ", " · ")
        self._context_label = ""
        # Cumulative session token accounting for the /cost command.
        self._session_output_tokens = 0
        self._last_context_tokens = 0
        self.answer_renderer = TerminalAnswerRenderer(self.console)
        self._turn_runner_accepts_approval = self._accepts_approval_handler(turn_runner)
        # Active mid-turn steering capture (set while a turn runs); lets the user
        # type extra guidance that the agent picks up at the next round boundary.
        self._steering_capture: _SteeringCapture | None = None

    def run(self) -> int:
        self.screen.enter()
        self._install_resize_handler()
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
            self._remove_resize_handler()
            self.screen.exit()
            self._print_resume_hint()

    def _install_resize_handler(self) -> None:
        """Redraw the composer immediately when the terminal is resized.

        Without this, the prompt box keeps the old width until the next keystroke.
        SIGWINCH exists only on POSIX and signal handlers can only be set from the
        main thread, so both are guarded."""
        self._prev_winch_handler = None
        if not self.screen.interactive:
            return
        import signal
        import threading

        if not hasattr(signal, "SIGWINCH") or threading.current_thread() is not threading.main_thread():
            return

        def _on_resize(_signum, _frame) -> None:
            try:
                self.screen.redraw()
            except Exception:  # noqa: BLE001 - a redraw must never crash the session
                pass

        try:
            self._prev_winch_handler = signal.signal(signal.SIGWINCH, _on_resize)
        except (ValueError, OSError):
            self._prev_winch_handler = None

    def _remove_resize_handler(self) -> None:
        if getattr(self, "_prev_winch_handler", None) is None:
            return
        import signal

        if not hasattr(signal, "SIGWINCH"):
            return
        try:
            signal.signal(signal.SIGWINCH, self._prev_winch_handler)
        except (ValueError, OSError, TypeError):
            pass

    def _print_resume_hint(self) -> None:
        """On exit, tell the user how to resume this conversation later.

        Only shown once the session has real history to resume; resuming an
        empty session would be pointless."""
        if not self._had_turn:
            return
        lines = [
            "",
            "이 세션을 이어서 진행하려면:",
            "  allcode --continue            (이 작업 폴더의 가장 최근 세션)",
        ]
        if self._session_id:
            lines.append(f"  allcode --resume {self._session_id}   (이 세션을 직접 지정)")
        self.stdout.write("\n".join(lines) + "\n")
        self.stdout.flush()

    async def handle_agent_event(self, event: AgentEvent) -> None:
        if event.event_type == "model_metrics_recorded":
            self._update_context_label(event.data or {})
            return
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
        self._had_turn = True
        self._print_user_prompt(prompt)
        # @path mentions: the typed prompt is shown verbatim, but the agent
        # receives the referenced file/dir contents appended as context.
        agent_prompt, mentioned = expand_mentions(prompt, self._cwd)
        if mentioned:
            self._print_status("첨부: " + ", ".join("@" + name for name in mentioned))
        self._stream_started = False
        self._stream_buffer = ""
        self._stream_markdown_buffer.reset()
        self.answer_renderer.reset()
        self._final_answer_rendered = False
        self._last_status = ""
        self._running_started_at = time.monotonic()
        self._render_running_composer(messages.MODEL_REQUEST_STATUS)
        try:
            asyncio.run(self._run_turn_with_ticker(agent_prompt))
        except KeyboardInterrupt:
            self.stderr.write("\nInterrupted.\n")
        except Exception as exc:
            self.error_console.print(f"[bold red]오류:[/] {exc}")
        finally:
            elapsed = (time.monotonic() - self._running_started_at) if self._running_started_at else 0.0
            self._finish_running_composer()
            self._notify_turn_complete(elapsed)

    def _notify_turn_complete(self, elapsed: float) -> None:
        """Ring the terminal bell after a long turn so the user can step away.

        Only fires when the turn ran past a threshold, so quick answers don't
        beep. The bell is portable; an OS notification is attempted best-effort."""
        if elapsed < self._NOTIFY_AFTER_SECONDS:
            return
        try:
            self.stdout.write("\a")
            self.stdout.flush()
        except Exception:  # noqa: BLE001
            pass

    async def _run_turn_with_ticker(self, prompt: str) -> None:
        # Animate the spinner/elapsed counter while the turn runs, including the
        # model "thinking" phase before the first token arrives (no agent events
        # fire then, so without this the spinner would freeze). The ticker shares
        # the turn's event loop, so repaints interleave safely with stream writes
        # at await boundaries — no cross-thread terminal contention.
        ticker = asyncio.create_task(self._spinner_ticker())
        capture = _SteeringCapture(self.stdin, getattr(self.turn_runner, "steering", None))
        self._steering_capture = capture
        capture.start()
        try:
            await self._run_turn(prompt)
        finally:
            capture.stop()
            self._steering_capture = None
            ticker.cancel()
            try:
                await ticker
            except asyncio.CancelledError:
                pass

    async def _spinner_ticker(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.2)
                # Keep whatever status the latest real event set; just re-tick the
                # spinner frame and elapsed counter.
                self._render_running_composer(self._composer_status)
        except asyncio.CancelledError:
            return

    async def _run_turn(self, prompt: str) -> None:
        if self._turn_runner_accepts_approval:
            await self.turn_runner(prompt, self.handle_agent_event, self.handle_approval_request)
            return
        await self.turn_runner(prompt, self.handle_agent_event)

    async def handle_approval_request(self, request: ApprovalRequest) -> ApprovalAction:
        # Pause mid-turn steering capture so the approval response (read from the
        # same stdin) is never grabbed by the steering reader thread.
        if self._steering_capture is not None:
            self._steering_capture.pause()
        try:
            return await self._handle_approval_request(request)
        finally:
            if self._steering_capture is not None:
                self._steering_capture.resume()

    async def _handle_approval_request(self, request: ApprovalRequest) -> ApprovalAction:
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
        stripped = command.strip()
        # /cost and /context are one unified usage view (session tokens +
        # context window), collected here from round metrics.
        if stripped in {"/cost", "/context"}:
            self._render_command_panel("사용량", self._usage_summary())
            return None
        if stripped.split(maxsplit=1)[0] == "/theme":
            self._render_command_panel("테마", self._switch_theme(stripped))
            return None
        # Bare /status shows the usage/status panel; "/status last" (and other
        # args) fall through to the diagnostics backend.
        if stripped == "/status":
            self._render_status(stripped)
            return None
        result = asyncio.run(self.slash_handler.handle(command))
        if result.clear_transcript:
            self._clear_screen()
        if result.message:
            self.answer_renderer.reset()
            # Present informational command output in the same polished framed
            # panel as /status; a command that expands into a turn prompt is left
            # to render as a normal turn below.
            if result.submit_prompt:
                self._print_assistant_block(result.message)
            else:
                self._render_command_panel(self._command_title(stripped), result.message)
        if result.exit_requested:
            return 0
        if result.submit_prompt:
            # A custom command expands to a prompt that runs as a normal turn.
            self._run_agent_prompt(result.submit_prompt)
        return None

    @staticmethod
    def _command_title(command: str) -> str:
        """A friendly panel title for a slash command (falls back to the name)."""
        name = command.strip().split(maxsplit=1)[0].lstrip("/").lower()
        titles = {
            "help": "도움말",
            "agents": "에이전트",
            "resume": "세션 재개",
            "memory": "메모리",
            "compact": "대화 압축",
            "init": "초기화",
            "mcp": "MCP",
            "model": "모델",
            "config": "설정",
            "clear": "화면 정리",
            "status": "상태",
            "doctor": "진단",
            "tools": "도구",
            "approval": "승인 모드",
            "permissions": "권한",
        }
        return titles.get(name, f"/{name}" if name else "명령")

    def _print_header(self) -> None:
        # No trailing blank line here: the composer draws its own one-line
        # separator above the prompt, so the banner sits one blank line above
        # the prompt without a wasteful gap.
        self.console.print(logo_text(self.app_info))

    def _print_user_prompt(self, prompt: str) -> None:
        self._prepare_body_output()
        # A blank line separates turns. The submitted prompt is rendered in a
        # distinct accent colour with a "›" marker so it reads unmistakably as the
        # user's input, clearly set apart from the dim "•" assistant answer that
        # follows. Built with Text (not console markup) so "[" in the prompt is not
        # interpreted as a style tag.
        self.console.print()
        line = Text()
        line.append("› ", style="bold #61afef")
        line.append(prompt, style="#61afef")
        self.console.print(line)

    def _print_assistant_block(self, text: str) -> None:
        self._prepare_body_output()
        self.answer_renderer.render(sanitize_channel_markup(text))
        self.console.print()

    def _print_assistant_stream_chunk(self, text: str) -> None:
        self._prepare_body_output()
        self.answer_renderer.render(sanitize_channel_markup(text))

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
        # Render a file edit as a colored unified diff (Codex-style): added lines
        # on a green wash, removed lines on a red wash, hunk headers on a slate
        # wash. The line-spanning background (padded to the screen width) makes a
        # change read as a real diff. Indented two columns so it sits under the
        # "• tool" summary row.
        if not diff.strip():
            return
        self._prepare_body_output()
        theme = self.screen.theme
        lines = diff.splitlines()
        width = max(40, self.screen.width)
        for raw in lines[:max_lines]:
            if raw.startswith("@@"):
                style = f"bold {theme.diff_hunk_fg} on {theme.diff_hunk_bg}"
            elif raw.startswith("+"):
                style = f"bold {theme.diff_add_fg} on {theme.diff_add_bg}"
            elif raw.startswith("-"):
                style = f"bold {theme.diff_del_fg} on {theme.diff_del_bg}"
            else:
                style = f"{theme.diff_ctx_fg} on {theme.diff_ctx_bg}"
            text = Text("  ")
            # Pad the line to the screen width so the background wash spans the
            # whole row rather than just the characters.
            text.append(raw.ljust(width - 2), style=style)
            self.console.print(text, no_wrap=True, crop=True)
        if len(lines) > max_lines:
            self.console.print(Text(f"  ... {len(lines) - max_lines} more diff lines ...", style="dim"))
        self._render_running_composer()

    def _usage_summary(self) -> str:
        """Unified /cost · /context view: this session's token spend and the
        current context-window size."""

        def fmt(value: int) -> str:
            return f"{value / 1000:.1f}k" if value >= 1000 else str(value)

        if not self._session_output_tokens and not self._last_context_tokens:
            return "아직 이 세션의 토큰 사용량 정보가 없습니다. 한 번 질문한 뒤 다시 확인하세요."
        return (
            "이번 세션 토큰·컨텍스트 사용 현황\n"
            f"- 누적 생성(출력) 토큰: {fmt(self._session_output_tokens)}\n"
            f"- 최근 요청 컨텍스트: {fmt(self._last_context_tokens)} 토큰\n"
            "- 컨텍스트를 줄이려면 `/compact` 로 대화를 압축하세요."
        )

    def _render_status(self, command: str) -> None:
        """Render /status as a polished panel: a colored daily token-usage gauge,
        per-model usage bars, and a status-analysis table. Drawn with Rich (not the
        markdown renderer) so alignment is preserved. Renders even on first launch
        (0% gauge)."""
        body: list = [self._gauge_renderable(), Text()]
        model_gauges = self._model_gauges_renderable()
        if model_gauges is not None:
            body.append(Text("모델별 토큰 사용량", style="bold"))
            body.append(model_gauges)
            body.append(Text())
        body.append(Text("상태 분석", style="bold"))
        body.append(self._metric_table(self._status_analysis_pairs()))

        panel = Panel(
            Group(*body),
            title="상태",
            title_align="left",
            border_style=self.screen.theme.accent,
            padding=(1, 2),
        )
        self._print_panel(panel)

    def _print_panel(self, panel: Panel) -> None:
        """Render a Rich Panel through a width-pinned console so the polished
        framed layout is preserved (the default console falls back to 80 cols
        for non-tty/captured output and would crop wider content). Writes flow
        through the body-counting proxy so the composer stays positioned."""
        self._prepare_body_output()
        panel_console = Console(
            file=self.screen.stdout,
            force_terminal=self.screen.interactive,
            color_system="truecolor" if self.screen.interactive else None,
            width=self.screen.width,
            highlight=False,
        )
        panel_console.print(panel)
        self.console.print()

    def _render_command_panel(self, title: str, message: str) -> None:
        """Render a slash command's output in the same polished framed style as
        /status: the message (markdown) inside an accent-bordered panel."""
        if not message.strip():
            return
        theme = self.screen.theme
        panel = Panel(
            Markdown(message),
            title=title,
            title_align="left",
            border_style=theme.accent,
            padding=(1, 2),
        )
        self._print_panel(panel)

    @staticmethod
    def _gauge_bar(used: int, maximum: int, *, width: int = 30) -> Text:
        """A single colored fill/empty bar for `used` against `maximum`."""
        ratio = gauge_fraction(used, maximum)
        filled = min(width, max(1 if used > 0 else 0, round(ratio * width)))
        color = "green" if ratio < 0.75 else "yellow" if ratio < 1.0 else "red"
        bar = Text()
        bar.append("█" * filled, style=color)
        bar.append("░" * (width - filled), style="grey37")
        return bar

    def _gauge_renderable(self) -> Text:
        used = self._usage.today_total()
        maximum = DAILY_TOKEN_BUDGET
        ratio = gauge_fraction(used, maximum)
        line = Text()
        line.append("오늘 토큰 사용량 ", style="bold")
        line.append(f"(하루 추정치 {fmt_tokens(maximum)})\n", style="dim")
        line.append_text(self._gauge_bar(used, maximum))
        line.append(f"  {ratio * 100:.0f}%  ", style="bold")
        line.append(f"{fmt_tokens(used)} / {fmt_tokens(maximum)} 토큰", style="dim")
        return line

    def _model_gauges_renderable(self) -> Table | None:
        """One gauge bar per model for today, aggregated from the models the
        agent actually ran (e.g. the ultra routing model vs the implementation/
        max editor model). Each bar fills against the same daily budget so the
        models are directly comparable. Returns None until a model reports usage."""
        by_model = self._usage.today_by_model()
        if not by_model:
            return None
        maximum = DAILY_TOKEN_BUDGET
        table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2, 0, 0))
        table.add_column(style="bold", no_wrap=True)  # model name
        table.add_column(no_wrap=True)  # bar
        table.add_column(justify="right", style="bold", no_wrap=True)  # percent
        table.add_column(justify="right", style="cyan", no_wrap=True)  # tokens
        for name, tokens in by_model.items():
            ratio = gauge_fraction(tokens, maximum)
            table.add_row(
                name.split("/")[-1],
                self._gauge_bar(tokens, maximum),
                f"{ratio * 100:.0f}%",
                f"{fmt_tokens(tokens)} 토큰",
            )
        return table

    def _status_analysis_pairs(self) -> list[tuple[str, str]]:
        """Status-analysis facts (separate from the backend session diagnostics):
        workspace, session, model/approval, git state, and today's usage against
        the daily budget. Helps a developer size up the session at a glance."""
        pairs: list[tuple[str, str]] = []
        cwd_disp = str(self._cwd)
        try:
            home = str(Path.home())
            if cwd_disp.startswith(home):
                cwd_disp = "~" + cwd_disp[len(home):]
        except Exception:  # noqa: BLE001 - display only
            pass
        pairs.append(("작업 디렉터리", cwd_disp))
        pairs.append(("세션", self._session_id[:8] if self._session_id else "신규 세션"))
        for token in self.app_info.split("|"):
            token = token.strip()
            if token.lower().startswith("model:"):
                pairs.append(("모델", token.split(":", 1)[1].strip()))
            elif token.lower().startswith("approval:"):
                pairs.append(("승인 모드", token.split(":", 1)[1].strip()))
        git = self._git_brief()
        if git:
            pairs.append(("Git", git))
        used = self._usage.today_total()
        remaining = max(0, DAILY_TOKEN_BUDGET - used)
        pct = (used / DAILY_TOKEN_BUDGET * 100) if DAILY_TOKEN_BUDGET else 0
        pairs.append(("오늘 사용량", f"{fmt_tokens(used)} / {fmt_tokens(DAILY_TOKEN_BUDGET)} ({pct:.0f}%)"))
        pairs.append(("남은 예산", fmt_tokens(remaining)))
        pairs.append(("최근 컨텍스트", f"{fmt_tokens(self._last_context_tokens)} 토큰"))
        pairs.append(("세션 출력", f"{fmt_tokens(self._session_output_tokens)} 토큰"))
        models = self._usage.today_by_model()
        if models:
            pairs.append(("활성 모델 수", str(len(models))))
        return pairs

    def _git_brief(self) -> str:
        """Current branch and dirty-file count for the workspace, or '' if not a
        git repo. Uses git directly (no agent imports) and fails quiet."""
        import subprocess

        try:
            branch = subprocess.run(
                ["git", "-C", str(self._cwd), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=2,
            )
            if branch.returncode != 0:
                return ""
            status = subprocess.run(
                ["git", "-C", str(self._cwd), "status", "--porcelain"],
                capture_output=True, text=True, timeout=2,
            )
            changed = len([line for line in status.stdout.splitlines() if line.strip()])
            state = "clean" if changed == 0 else f"{changed} changed"
            return f"{branch.stdout.strip()} ({state})"
        except Exception:  # noqa: BLE001 - status panel must still render
            return ""

    def _metric_table(self, pairs: list[tuple[str, str]]) -> Table:
        groups = max(1, columns_for_width(self.screen.width))
        table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2, 0, 0))
        for _ in range(groups):
            table.add_column(style="dim", no_wrap=True)  # label
            table.add_column(justify="right", style="cyan", no_wrap=True)  # value
        rows = (len(pairs) + groups - 1) // groups
        for row in range(rows):
            cells: list[str] = []
            for col in range(groups):
                index = row + col * rows  # column-major so each column reads top-to-bottom
                if index < len(pairs):
                    label, value = pairs[index]
                    cells.extend([label, str(value)])
                else:
                    cells.extend(["", ""])
            table.add_row(*cells)
        return table

    def _switch_theme(self, command: str) -> str:
        parts = command.split(maxsplit=1)
        if len(parts) < 2 or parts[1].strip().lower() not in {"dark", "light"}:
            return "사용법: /theme dark | /theme light"
        name = parts[1].strip().lower()
        self.screen.theme = TerminalTheme.named(name)
        return f"테마를 '{name}'(으)로 변경했습니다."

    def _update_context_label(self, data: dict) -> None:
        """Refresh the persistent context-usage indicator in the footer from the
        latest model round metrics. Uses real token counts when the model reports
        them, otherwise approximates from the request size (~4 chars/token)."""

        usage = data.get("usage") if isinstance(data, dict) else None
        tokens = None
        if isinstance(usage, dict):
            tokens = usage.get("prompt_tokens") or usage.get("total_tokens")
            completion = usage.get("completion_tokens")
            if isinstance(completion, int) and completion > 0:
                self._session_output_tokens += completion
            # Record this round's real token spend toward today's usage gauge.
            prompt_t = usage.get("prompt_tokens")
            round_total = 0
            if isinstance(prompt_t, int) and prompt_t > 0:
                round_total += prompt_t
            if isinstance(completion, int) and completion > 0:
                round_total += completion
            if round_total == 0 and isinstance(usage.get("total_tokens"), int):
                round_total = usage["total_tokens"]
            if round_total > 0:
                model = data.get("model") if isinstance(data, dict) else None
                self._usage.add(round_total, model=model if isinstance(model, str) else None)
        if isinstance(tokens, int) and tokens > 0:
            self._last_context_tokens = tokens
        approx = False
        if not tokens:
            chars = data.get("prompt_chars") or data.get("request_chars")
            if isinstance(chars, int) and chars > 0:
                tokens = max(1, chars // 4)
                approx = True
        if not tokens:
            return
        prefix = "~" if approx else ""
        if tokens >= 1000:
            shown = f"{prefix}{tokens / 1000:.1f}k"
        else:
            shown = f"{prefix}{tokens}"
        self._context_label = f"컨텍스트 {shown} 토큰"
        footer = self._base_footer
        if self._context_label:
            footer = f"{footer} · {self._context_label}"
        self.input_editor.footer = footer

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
    session_id: str | None = None,
) -> int:
    return TerminalSession(
        turn_runner=turn_runner,
        app_info=app_info,
        slash_handler=slash_handler,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
        session_id=session_id,
    ).run()

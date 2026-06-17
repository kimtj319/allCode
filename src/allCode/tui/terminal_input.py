"""Codex-style terminal input editor."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from allCode.tui.command_registry import CommandRegistry
from allCode.tui.terminal_activity import ActivityProps
from allCode.tui.terminal_bottom_pane import BottomPaneRenderInput, TerminalBottomPane
from allCode.tui.terminal_completion import CompletionState, TerminalCompleter
from allCode.tui.terminal_footer import FooterProps
from allCode.tui.terminal_history import TerminalHistory
from allCode.tui.terminal_keymap import EditorCommand, TerminalKeymap
from allCode.tui.terminal_keys import TerminalKeyReader
from allCode.tui.terminal_paste_sanitizer import normalize_pasted_text
from allCode.tui.terminal_overlay import OverlayItem, OverlayView
from allCode.tui.terminal_paste import PasteManager
from allCode.tui.terminal_screen import TerminalScreen
from allCode.tui.terminal_text_area import TerminalTextArea
from allCode.tui.terminal_width import display_width, wrap_display_width

# Display width of the composer prompt prefix ("› " / "  "), where the input
# text and caret begin.
_PROMPT_PREFIX_WIDTH = 2


@dataclass
class InputRenderState:
    lines: list[str]
    cursor_row: int
    cursor_col: int
    completions: list[str] = field(default_factory=list)


class TerminalInputEditor:
    """Read one user prompt with multiline editing, history, completion, and paste support."""

    def __init__(
        self,
        *,
        screen: TerminalScreen,
        stdin: TextIO,
        stdout: TextIO,
        registry: CommandRegistry,
        cwd: Path,
        footer: str = "",
    ) -> None:
        self.screen = screen
        self.stdin = stdin
        self.stdout = stdout
        self.history = TerminalHistory()
        self.completer = TerminalCompleter(registry=registry, cwd=cwd)
        self.key_reader = TerminalKeyReader(stdin)
        self.keymap = TerminalKeymap()
        self.bottom_pane = TerminalBottomPane()
        self.paste_manager = PasteManager()
        self.footer = footer
        self._completion_state: CompletionState | None = None

    def read_prompt(self) -> str:
        if not self.screen.interactive:
            return self._read_line_mode()
        if not self.key_reader.can_use_raw_mode():
            return self._read_interactive_line_mode()
        return self._read_raw_prompt()

    def _read_line_mode(self) -> str:
        self.stdout.write("\n  › ")
        self.stdout.flush()
        line = self.stdin.readline()
        self.stdout.write("\n")
        if line == "":
            raise EOFError
        return normalize_pasted_text(line.rstrip("\n"))

    def _read_interactive_line_mode(self) -> str:
        self.screen.render_input_panel(lines=[""], cursor_row=0, cursor_col=3, footer=self.footer)
        line = self.stdin.readline()
        self.screen.clear_input_panel()
        if line == "":
            raise EOFError
        return normalize_pasted_text(line.rstrip("\n"))

    def render_runtime_frame(self, *, activity: ActivityProps | None = None) -> None:
        """Render an empty composer frame while an agent turn is running."""

        frame = self.bottom_pane.frame(
            BottomPaneRenderInput(
                input_lines=[""],
                cursor_row=0,
                cursor_col=3,
                footer=FooterProps(mode="task_running" if activity and activity.running else "composer_empty", status_line=self.footer),
                activity=activity,
            ),
            width=self.screen.width,
        )
        self.screen.render_bottom_frame(frame)

    def _read_raw_prompt(self) -> str:
        area = TerminalTextArea()
        self.paste_manager.clear()
        self._completion_state = None
        with self.key_reader.raw_mode(self.stdout):
            self._render(area)
            while True:
                key = self.key_reader.read_key()
                submitted = self._handle_key(area, key)
                if submitted is not None:
                    self.screen.clear_input_panel()
                    self.history.append(submitted)
                    return self.paste_manager.expand(submitted)
                self._render(area)

    def _handle_key(self, area: TerminalTextArea, key: str) -> str | None:
        command = self.keymap.resolve(key)
        submitted = self._handle_command(area, command)
        self.paste_manager.prune(area.text, element_labels=area.element_labels(kind="large_paste"))
        return submitted

    def _handle_command(self, area: TerminalTextArea, command: EditorCommand) -> str | None:
        if command.name == "cancel_or_interrupt":
            raise KeyboardInterrupt
        if command.name == "eof_or_delete_forward":
            if not area.text:
                raise EOFError
            area.delete_forward()
            return None
        if command.name == "submit":
            return area.text if area.text.strip() else None
        if command.name == "insert_newline":
            area.insert("\n")
        elif command.name == "delete_backward":
            area.delete_backward()
        elif command.name == "delete_forward":
            area.delete_forward()
        elif command.name == "move_left":
            area.move_left()
        elif command.name == "move_right":
            area.move_right()
        elif command.name == "move_word_left":
            area.move_word_left()
        elif command.name == "move_word_right":
            area.move_word_right()
        elif command.name == "move_up":
            if not self._navigate_completion(area, -1):
                self._move_up_or_history(area)
        elif command.name == "move_down":
            if not self._navigate_completion(area, +1):
                self._move_down_or_history(area)
        elif command.name == "move_line_start":
            area.move_line_start()
        elif command.name == "move_line_end":
            area.move_line_end()
        elif command.name == "kill_line_start":
            area.kill_to_line_start()
        elif command.name == "kill_line_end":
            area.kill_to_line_end()
        elif command.name == "yank":
            area.yank()
        elif command.name == "delete_backward_word":
            area.delete_backward_word()
        elif command.name == "undo":
            area.undo()
        elif command.name == "redo":
            area.redo()
        elif command.name == "complete_or_queue":
            self._apply_completion(area)
            return None
        elif command.name == "paste":
            self.paste_manager.insert_paste(area, command.text)
        elif command.name == "insert_char":
            area.insert(command.text)
        # Tab cycling and arrow-key completion navigation keep the active
        # completion alive; any other key dismisses the suggestion overlay.
        if command.name == "complete_or_queue":
            pass
        elif command.name in {"move_up", "move_down"} and self._completion_state is not None:
            pass
        else:
            self._completion_state = None
        return None

    def _move_up_or_history(self, area: TerminalTextArea) -> None:
        if area.is_cursor_on_first_line():
            previous = self.history.previous(area.text)
            if previous is not None:
                area.set_text(previous)
            return
        area.move_up()

    def _move_down_or_history(self, area: TerminalTextArea) -> None:
        if area.is_cursor_on_last_line():
            next_entry = self.history.next()
            if next_entry is not None:
                area.set_text(next_entry)
            return
        area.move_down()

    def _apply_completion(self, area: TerminalTextArea) -> None:
        state = self._completion_state
        if state is None:
            state = self.completer.complete(area.text, area.cursor)
            if state is None:
                return
            self._completion_state = state
            candidate = state.current()
        else:
            candidate = state.advance()
        self._insert_candidate(area, candidate)

    def _navigate_completion(self, area: TerminalTextArea, delta: int) -> bool:
        """Move the slash/path suggestion selection with ↑/↓.

        Returns True when a completion was active (or could be started for the
        current token) and was navigated; False when there is nothing to
        complete, so the caller can fall back to history/cursor movement."""
        state = self._completion_state
        if state is None:
            state = self.completer.complete(area.text, area.cursor)
            if state is None:
                return False
            self._completion_state = state
            # ↓ starts at the first suggestion, ↑ at the last (wrap-around).
            state.selected = 0 if delta > 0 else len(state.candidates) - 1
            candidate = state.current()
        else:
            candidate = state.move(delta)
        self._insert_candidate(area, candidate)
        return True

    def _insert_candidate(self, area: TerminalTextArea, candidate) -> None:
        state = self._completion_state
        text = area.text[: state.start] + candidate.replacement + area.text[state.end :]
        state.end = state.start + len(candidate.replacement)
        area.set_text(text, cursor=state.end)

    def _render(self, area: TerminalTextArea) -> None:
        view = self._render_state(area)
        frame = self.bottom_pane.frame(
            BottomPaneRenderInput(
                input_lines=view.lines,
                cursor_row=view.cursor_row,
                cursor_col=view.cursor_col,
                overlay=self._overlay_for(area),
                footer=FooterProps(
                    mode="composer_has_draft" if area.text else "composer_empty",
                    status_line=self.footer,
                ),
            ),
            width=self.screen.width,
        )
        self.screen.render_bottom_frame(frame)

    def _render_state(self, area: TerminalTextArea) -> InputRenderState:
        # Text wraps inside the input box: terminal width minus the box borders
        # ("│ " + " │" = 4) and the two-column prompt prefix.
        width = max(8, self.screen.width - 6)
        visual_lines: list[str] = []
        cursor_position = area.cursor_position()
        cursor_row = 0
        # The prompt prefix ("› " on the first line, "  " on wrapped lines) is two
        # display columns wide, so the text — and the cursor — start two columns
        # in. Using 3 here put the caret one cell past the text end; for wide
        # (CJK) input that gap is especially visible during IME composition.
        cursor_col = _PROMPT_PREFIX_WIDTH
        for line_index, line in enumerate(area.lines()):
            chunks = wrap_display_width(line, width)
            if line_index == cursor_position.line:
                display_col = display_width(line[: cursor_position.column])
                if display_col > 0 and display_col % width == 0:
                    wrapped_row = (display_col - 1) // width
                    wrapped_column = width
                else:
                    wrapped_row = display_col // width
                    wrapped_column = display_col % width
                cursor_row = len(visual_lines) + min(wrapped_row, len(chunks) - 1)
                cursor_col = _PROMPT_PREFIX_WIDTH + wrapped_column
            visual_lines.extend(chunks)
        return InputRenderState(lines=visual_lines or [""], cursor_row=cursor_row, cursor_col=cursor_col)

    def _overlay_for(self, area: TerminalTextArea) -> OverlayView | None:
        # An active Tab-cycle completion takes precedence; otherwise show a live
        # slash-command menu as the user types (Codex-style), without modifying
        # the draft text.
        completion = self._completion_overlay()
        if completion is not None:
            return completion
        return self._slash_menu_overlay(area) or self._mention_menu_overlay(area)

    _COMPLETION_WINDOW = 6

    def _completion_overlay(self) -> OverlayView | None:
        state = self._completion_state
        if state is None:
            return None
        # Show a scrolling window of candidates that always keeps the selected
        # item visible. A fixed candidates[:5] slice froze the menu (and hid the
        # highlight) once the selection moved past the first few with ↑/↓.
        total = len(state.candidates)
        window = self._COMPLETION_WINDOW
        if total <= window:
            start = 0
        else:
            start = min(max(0, state.selected - window // 2), total - window)
        items: list[OverlayItem] = []
        for offset, candidate in enumerate(state.candidates[start : start + window]):
            items.append(
                OverlayItem(
                    label=candidate.label,
                    description=candidate.description,
                    selected=(start + offset) == state.selected,
                )
            )
        return OverlayView(kind="completion", items=items)

    def _slash_menu_overlay(self, area: TerminalTextArea) -> OverlayView | None:
        text = area.text
        if "\n" in text or not text.startswith("/"):
            return None
        query = text.strip().lower()
        commands = self.completer.registry.all()
        matches = [command for command in commands if command.name.lower().startswith(query)]
        if not matches:
            matches = self.completer.registry.filter(query)
        if not matches:
            return None
        items = [OverlayItem(label=command.name, description=command.description) for command in matches[:6]]
        return OverlayView(kind="completion", items=items)

    def _mention_menu_overlay(self, area: TerminalTextArea) -> OverlayView | None:
        # Live workspace file picker while typing an "@path" token (Codex-style),
        # reusing the Tab path-completion candidates as a display-only overlay.
        # Defensive: an overlay must never break the composer render.
        try:
            state = self.completer._path_completion(area.text, area.cursor)
        except Exception:
            return None
        if state is None:
            return None
        items = [
            OverlayItem(label=candidate.label, description=candidate.description)
            for candidate in state.candidates[:6]
        ]
        return OverlayView(kind="completion", items=items) if items else None

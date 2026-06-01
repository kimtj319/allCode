"""Codex-style terminal input editor."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from allCode.tui.command_registry import CommandRegistry
from allCode.tui.terminal_bottom_pane import BottomPaneRenderInput, TerminalBottomPane
from allCode.tui.terminal_completion import CompletionState, TerminalCompleter
from allCode.tui.terminal_footer import FooterProps
from allCode.tui.terminal_history import TerminalHistory
from allCode.tui.terminal_keymap import EditorCommand, TerminalKeymap
from allCode.tui.terminal_keys import TerminalKeyReader
from allCode.tui.terminal_overlay import OverlayItem, OverlayView
from allCode.tui.terminal_paste import PasteManager
from allCode.tui.terminal_screen import TerminalScreen
from allCode.tui.terminal_text_area import TerminalTextArea
from allCode.tui.terminal_width import display_width, wrap_display_width


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
        return line.rstrip("\n")

    def _read_interactive_line_mode(self) -> str:
        self.screen.render_input_panel(lines=[""], cursor_row=0, cursor_col=3, footer=self.footer)
        line = self.stdin.readline()
        self.screen.clear_input_panel()
        if line == "":
            raise EOFError
        return line.rstrip("\n")

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
            self._move_up_or_history(area)
        elif command.name == "move_down":
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
        if command.name != "complete_or_queue":
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
                overlay=self._completion_overlay(),
                footer=FooterProps(
                    mode="composer_has_draft" if area.text else "composer_empty",
                    status_line=self.footer,
                ),
            ),
            width=self.screen.width,
        )
        self.screen.render_bottom_frame(frame)

    def _render_state(self, area: TerminalTextArea) -> InputRenderState:
        width = max(10, self.screen.width - 3)
        visual_lines: list[str] = []
        cursor_position = area.cursor_position()
        cursor_row = 0
        cursor_col = 3
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
                cursor_col = 3 + wrapped_column
            visual_lines.extend(chunks)
        return InputRenderState(lines=visual_lines or [""], cursor_row=cursor_row, cursor_col=cursor_col)

    def _completion_overlay(self) -> OverlayView | None:
        state = self._completion_state
        if state is None:
            return None
        items: list[OverlayItem] = []
        for index, candidate in enumerate(state.candidates[:5]):
            items.append(OverlayItem(label=candidate.label, description=candidate.description, selected=index == state.selected))
        return OverlayView(kind="completion", items=items)

def is_real_stdio(stdin: TextIO = sys.stdin) -> bool:
    isatty = getattr(stdin, "isatty", None)
    return bool(isatty and isatty())

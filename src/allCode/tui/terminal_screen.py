"""Low-level terminal screen controls for the interactive shell."""

from __future__ import annotations

import shutil
import os
from dataclasses import dataclass
from typing import TextIO

from allCode.tui.terminal_frame import StyledLine, TerminalFrame

@dataclass(frozen=True)
class TerminalTheme:
    prompt_fg: tuple[int, int, int] = (247, 247, 247)
    dim_fg: tuple[int, int, int] = (138, 138, 138)


class TerminalScreen:
    """Reserve a small bottom prompt area while body output scrolls above it."""

    reserved_rows = 3
    max_reserved_rows = 12

    def __init__(
        self,
        *,
        stdin: TextIO,
        stdout: TextIO,
        theme: TerminalTheme | None = None,
    ) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self.theme = theme or TerminalTheme()
        self.interactive = self._is_terminal(stdin) and self._is_terminal(stdout)
        self._entered = False

    @property
    def size(self) -> os.terminal_size:
        return shutil.get_terminal_size(fallback=(80, 24))

    @property
    def width(self) -> int:
        return max(20, self.size.columns)

    @property
    def height(self) -> int:
        return max(8, self.size.lines)

    @property
    def body_bottom(self) -> int:
        return max(1, self.height - self.reserved_rows)

    def enter(self) -> None:
        if not self.interactive:
            return
        self._entered = True
        self.stdout.write("\x1b[2J\x1b[H")
        self._apply_scroll_region()
        self.stdout.flush()

    def exit(self) -> None:
        if not self.interactive or not self._entered:
            return
        self.stdout.write("\x1b[r")
        self._clear_prompt_area()
        self.stdout.write(f"\x1b[{self.height};1H")
        self.stdout.flush()
        self._entered = False

    def clear_all(self) -> None:
        if not self.interactive:
            return
        self.stdout.write("\x1b[2J\x1b[H")
        self._apply_scroll_region()
        self.stdout.flush()

    def render_input_panel(
        self,
        *,
        lines: list[str],
        cursor_row: int,
        cursor_col: int,
        completions: list[str] | None = None,
        footer: str | None = None,
    ) -> None:
        frame = TerminalFrame(
            input_lines=[StyledLine(text=line) for line in lines],
            overlay_lines=[StyledLine(text=line, style="dim") for line in completions or []],
            footer_lines=[StyledLine(text=footer, style="dim")] if footer else [],
            cursor_row=cursor_row,
            cursor_col=cursor_col,
        )
        self.render_bottom_frame(frame)

    def render_bottom_frame(self, frame: TerminalFrame) -> None:
        if not self.interactive:
            return
        self.stdout.write("\x1b[?25l")
        try:
            footer_rows = len(frame.footer_lines)
            needed_rows = max(3, min(self.max_reserved_rows, frame.line_count + 2))
            self.set_reserved_rows(needed_rows)
            self._clear_prompt_area()
            start = self.height - self.reserved_rows + 1
            input_start = start + 1
            usable_rows = self.reserved_rows - 2 - footer_rows
            for index, line in enumerate(frame.input_lines[:usable_rows]):
                prefix = "› " if index == 0 else "  "
                row = input_start + index
                self.stdout.write(f"\x1b[{row};1H")
                self.stdout.write(f"{self._fg(self.theme.prompt_fg)}{prefix}\x1b[0m{line.text}")
            completion_start = input_start + min(len(frame.input_lines), usable_rows)
            for offset, line in enumerate(frame.overlay_lines[: max(0, usable_rows - len(frame.input_lines))]):
                self.stdout.write(f"\x1b[{completion_start + offset};1H")
                self.stdout.write(f"{self._fg(self.theme.dim_fg)}  {line.text}\x1b[0m")
            for offset, line in enumerate(frame.footer_lines):
                row = self.height - len(frame.footer_lines) + offset + 1
                self.stdout.write(f"\x1b[{row};1H")
                self.stdout.write(f"{self._fg(self.theme.dim_fg)}  {line.text[: max(0, self.width - 3)]}\x1b[0m")
            cursor_screen_row = min(input_start + frame.cursor_row, self.height)
            cursor_screen_col = max(1, min(self.width, 1 + frame.cursor_col))
            self.stdout.write(f"\x1b[{cursor_screen_row};{cursor_screen_col}H")
        finally:
            self.stdout.write("\x1b[?25h")
            self.stdout.flush()

    def set_reserved_rows(self, rows: int) -> None:
        rows = max(3, min(self.max_reserved_rows, rows, self.height - 1))
        if rows == self.reserved_rows:
            return
        self.reserved_rows = rows
        self._apply_scroll_region()

    def clear_input_panel(self) -> None:
        if not self.interactive:
            return
        self._clear_prompt_area()
        self.stdout.flush()

    def prepare_body_output(self) -> None:
        """Clear composer rows and move the cursor back into the scrollback area."""

        if not self.interactive:
            return
        self._clear_prompt_area()
        self._apply_scroll_region()
        self.stdout.write(f"\x1b[{self.body_bottom};1H")
        self.stdout.write("\n")
        self.stdout.flush()

    def _clear_prompt_area(self) -> None:
        start = self.height - self.reserved_rows + 1
        for row in range(start, self.height + 1):
            self.stdout.write(f"\x1b[{row};1H\x1b[2K")

    def _apply_scroll_region(self) -> None:
        self.stdout.write(f"\x1b[1;{self.body_bottom}r")

    @staticmethod
    def _is_terminal(stream: TextIO) -> bool:
        isatty = getattr(stream, "isatty", None)
        return bool(isatty and isatty())

    @staticmethod
    def _fg(rgb: tuple[int, int, int]) -> str:
        red, green, blue = rgb
        return f"\x1b[38;2;{red};{green};{blue}m"

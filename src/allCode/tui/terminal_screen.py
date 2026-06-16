"""Low-level terminal screen controls for the interactive shell."""

from __future__ import annotations

import shutil
import os
from dataclasses import dataclass
from typing import TextIO

from allCode.tui.terminal_frame import StyledLine, TerminalFrame
from allCode.tui.terminal_width import clip_display_width, display_width

@dataclass(frozen=True)
class TerminalTheme:
    prompt_fg: tuple[int, int, int] = (247, 247, 247)
    dim_fg: tuple[int, int, int] = (138, 138, 138)

    @classmethod
    def named(cls, name: str) -> "TerminalTheme":
        """Return a named preset: 'light' for light terminals, else the dark default."""
        if (name or "").strip().lower() == "light":
            return cls(prompt_fg=(20, 20, 20), dim_fg=(110, 110, 110))
        return cls()


class _BodyRowCounter:
    """Wrap stdout and count newlines so the screen knows where body output ends.

    Body text (assistant answers, prompts, the banner) is written through Rich's
    Console, which emits a ``\\n`` per visual line. The composer/activity panel is
    drawn with absolute cursor moves and emits no newlines, so counting newlines on
    this stream tracks how far body output has flowed without guessing Rich's
    wrapping.
    """

    def __init__(self, target: TextIO, screen: "TerminalScreen") -> None:
        self._target = target
        self._screen = screen

    def write(self, text: str) -> int:
        if text:
            newlines = text.count("\n")
            if newlines:
                self._screen._advance_body_rows(newlines)
            # Track whether body output left the cursor mid-row (no trailing
            # newline). The floating composer must not be drawn on a partial line
            # or it would clobber streamed text that hasn't been committed yet.
            self._screen._body_partial = not text.endswith("\n")
        return self._target.write(text)

    def flush(self) -> None:
        self._target.flush()

    def isatty(self) -> bool:
        isatty = getattr(self._target, "isatty", None)
        return bool(isatty and isatty())

    def __getattr__(self, name: str):
        return getattr(self._target, name)


class TerminalScreen:
    """Reserve a small bottom prompt area while body output scrolls above it."""

    # Start at the steady-state minimum for the boxed composer: blank separator +
    # box top border + prompt row + box bottom border + footer + margin. Beginning
    # here avoids a scroll on the first render that would push the banner's top
    # border off-screen.
    reserved_rows = 6
    max_reserved_rows = 14

    def __init__(
        self,
        *,
        stdin: TextIO,
        stdout: TextIO,
        theme: TerminalTheme | None = None,
    ) -> None:
        self.stdin = stdin
        self.theme = theme or TerminalTheme()
        self.interactive = self._is_terminal(stdin) and self._is_terminal(stdout)
        self._entered = False
        self._applied_height: int | None = None
        # Next free body row (1-based). Body output flows from here; once it
        # reaches body_bottom it stays clamped there and content scrolls.
        self._body_row = 1
        # True when the last body write did not end in a newline (cursor sits
        # mid-row). The float floor is pushed one row down in that case.
        self._body_partial = False
        # Row where the composer block was last drawn. While body output is short
        # (e.g. just the banner) the composer floats right beneath it instead of
        # being pinned to the bottom, so the screen does not show a large empty gap
        # between the header and the prompt. It migrates down to the bottom as body
        # content grows. None means "not yet drawn" → defaults to the bottom.
        self._composer_top: int | None = None
        self._raw_stdout = stdout
        self.stdout: TextIO = _BodyRowCounter(stdout, self)

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

    def _advance_body_rows(self, count: int) -> None:
        self._body_row = min(self._body_row + count, self.body_bottom)

    def _composer_start(self) -> int:
        """Row where the composer block begins. It floats right under the body
        while there is room, and pins to the bottom once body output reaches the
        reserved area. A partial (un-newline-terminated) last body line pushes the
        floor down one row so the composer never overwrites uncommitted text."""

        bottom_start = self.height - self.reserved_rows + 1
        floor_row = self._body_row + (1 if self._body_partial else 0)
        if floor_row >= self.body_bottom:
            return bottom_start
        return max(1, floor_row)

    def enter(self) -> None:
        if not self.interactive:
            return
        self._entered = True
        self._body_row = 1
        self._raw_stdout.write("\x1b[2J\x1b[H")
        self._apply_scroll_region()
        self._raw_stdout.flush()

    def exit(self) -> None:
        if not self.interactive or not self._entered:
            return
        self._raw_stdout.write("\x1b[r")
        self._clear_prompt_area()
        self._raw_stdout.write(f"\x1b[{self.height};1H")
        self._raw_stdout.flush()
        self._entered = False

    def clear_all(self) -> None:
        if not self.interactive:
            return
        self._body_row = 1
        self._raw_stdout.write("\x1b[2J\x1b[H")
        self._apply_scroll_region()
        self._raw_stdout.flush()

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
        self._raw_stdout.write("\x1b[?25l")
        try:
            # +2 rows for the input box's top and bottom borders.
            needed_rows = max(4, min(self.max_reserved_rows, frame.line_count + 4))
            self.set_reserved_rows(needed_rows)
            start = self._composer_start()
            self._composer_top = start
            self._clear_prompt_area()
            # Codex separates the live composer from scrollback with blank space
            # rather than a full-width rule.
            self._write_line(start, "")
            row = start + 1

            for line in frame.activity_lines:
                if row >= self.height:
                    break
                if line.fg is not None and line.dim_suffix_at is not None:
                    self._write_pulse_line(row, line.text, line.dim_suffix_at, line.fg)
                else:
                    self._write_line(row, line.text, style=line.style)
                row += 1
            if frame.spacer_after_activity and row < self.height:
                self._write_line(row, "")
                row += 1

            # Draw the input inside a rounded border box for clear separation
            # (Claude Code-style). The box reserves two rows for borders.
            footer_rows = len(frame.footer_lines)
            box_top = row
            input_start = box_top + 1
            usable_rows = max(1, self.height - input_start - footer_rows - 1)
            shown_inputs = frame.input_lines[:usable_rows] or [StyledLine(text="")]
            self._write_box_border(box_top, top=True)
            for index, line in enumerate(shown_inputs):
                prefix = "› " if index == 0 else "  "
                self._write_box_input_row(input_start + index, prefix, line.text)
            box_bottom = input_start + len(shown_inputs)
            self._write_box_border(box_bottom, top=False)

            completion_start = box_bottom + 1
            shown_overlays = frame.overlay_lines[: max(0, usable_rows - len(shown_inputs))]
            for offset, line in enumerate(shown_overlays):
                self._write_line(completion_start + offset, f"  {line.text}", style=line.style)
            # Keep the footer (status line) attached to the bottom of the composer
            # block rather than the screen bottom, so a floating composer stays
            # compact instead of stranding the footer at the bottom of the screen.
            footer_start = completion_start + len(shown_overlays)
            for offset, line in enumerate(frame.footer_lines):
                footer_row = min(self.height, footer_start + offset)
                self._write_line(footer_row, f"  {line.text}", style=line.style)
            # Cursor: shift right by the box's "│ " (2 cells) past the prefix base.
            cursor_screen_row = min(input_start + frame.cursor_row, self.height)
            cursor_screen_col = max(1, min(self.width, 3 + frame.cursor_col))
            self._raw_stdout.write(f"\x1b[{cursor_screen_row};{cursor_screen_col}H")
        finally:
            self._raw_stdout.write("\x1b[?25h")
            self._raw_stdout.flush()

    def _write_box_border(self, row: int, *, top: bool) -> None:
        if row > self.height:
            return
        left, right = ("╭", "╮") if top else ("╰", "╯")
        line = left + "─" * max(0, self.width - 2) + right
        self._write_line(row, line, style="dim")

    def _write_box_input_row(self, row: int, prefix: str, text: str) -> None:
        if row > self.height:
            return
        inner = max(0, self.width - 4)  # content between "│ " and " │"
        body_text = clip_display_width(text, max(0, inner - display_width(prefix)))
        used = display_width(prefix) + display_width(body_text)
        pad = " " * max(0, inner - used)
        border = self._fg(self.theme.dim_fg)
        prompt = self._fg(self.theme.prompt_fg)
        self._raw_stdout.write(f"\x1b[{row};1H\x1b[2K")
        self._raw_stdout.write(f"{border}│\x1b[0m ")
        self._raw_stdout.write(f"{prompt}{prefix}\x1b[0m{body_text}{pad}")
        self._raw_stdout.write(f" {border}│\x1b[0m")

    def set_reserved_rows(self, rows: int) -> None:
        # Reserved height is monotonic (high-water) within a session: once the
        # running composer needs N rows we keep them, so the scroll region does
        # not thrash smaller↔larger every turn (which scrolled committed body
        # lines and produced visible jumps). It only ever grows.
        rows = max(self.reserved_rows, min(self.max_reserved_rows, rows, self.height - 1))
        if rows == self.reserved_rows:
            return
        delta = rows - self.reserved_rows
        if self._entered and self.interactive and self._applied_height == self.height:
            # Growing the reserved area shrinks the scroll region from the bottom.
            # Scroll the committed body up by `delta` first so the rows that are
            # about to become composer rows are blank instead of clobbering the
            # last committed body lines. Compute against the OLD body_bottom.
            # Write through the raw stream: these newlines shift existing content
            # UP, they are not new body output, so adjust the body row directly.
            old_body_bottom = max(1, self.height - self.reserved_rows)
            self._raw_stdout.write(f"\x1b[1;{old_body_bottom}r")
            self._raw_stdout.write(f"\x1b[{old_body_bottom};1H")
            self._raw_stdout.write("\n" * delta)
            self._body_row = max(1, self._body_row - delta)
        self.reserved_rows = rows
        self._apply_scroll_region()

    def clear_input_panel(self) -> None:
        if not self.interactive:
            return
        self._clear_prompt_area()
        self._raw_stdout.flush()

    def prepare_body_output(self) -> None:
        """Clear composer rows and move the cursor back into the scrollback area."""

        if not self.interactive:
            return
        self._clear_prompt_area()
        self._apply_scroll_region()
        target_row = min(max(1, self._body_row), self.body_bottom)
        self._raw_stdout.write(f"\x1b[{target_row};1H")
        self._raw_stdout.flush()

    def _clear_prompt_area(self) -> None:
        # Clear from where the composer currently belongs (derived from the live
        # body position, not a stale cached row) down to the bottom of the screen.
        # Deriving it live ensures body text written since the last composer draw
        # is never erased by the clear that precedes a redraw.
        start = self._composer_start()
        for row in range(start, self.height + 1):
            self._raw_stdout.write(f"\x1b[{row};1H\x1b[2K")

    def _apply_scroll_region(self) -> None:
        self._applied_height = self.height
        self._raw_stdout.write(f"\x1b[1;{self.body_bottom}r")

    def _separator(self) -> str:
        return "─" * self.width

    def _write_line(self, row: int, text: str, *, style: str = "normal") -> None:
        if row > self.height:
            return
        self._raw_stdout.write(f"\x1b[{row};1H\x1b[2K")
        prefix = self._fg(self.theme.dim_fg) if style == "dim" else ""
        suffix = "\x1b[0m" if prefix else ""
        self._raw_stdout.write(f"{prefix}{clip_display_width(text, self.width)}{suffix}")

    def _write_pulse_line(self, row: int, text: str, split: int, fg: tuple[int, int, int]) -> None:
        """Write an activity line whose leading "• <label>" breathes in `fg`
        (bold) while the trailing "(Ns • esc to interrupt)" stays dim."""

        if row > self.height:
            return
        clipped = clip_display_width(text, self.width)
        split = max(0, min(split, len(clipped)))
        head, tail = clipped[:split], clipped[split:]
        red, green, blue = fg
        self._raw_stdout.write(f"\x1b[{row};1H\x1b[2K")
        self._raw_stdout.write(f"\x1b[1m\x1b[38;2;{red};{green};{blue}m{head}\x1b[0m")
        if tail:
            self._raw_stdout.write(f"{self._fg(self.theme.dim_fg)}{tail}\x1b[0m")

    @staticmethod
    def _is_terminal(stream: TextIO) -> bool:
        isatty = getattr(stream, "isatty", None)
        return bool(isatty and isatty())

    @staticmethod
    def _fg(rgb: tuple[int, int, int]) -> str:
        red, green, blue = rgb
        return f"\x1b[38;2;{red};{green};{blue}m"

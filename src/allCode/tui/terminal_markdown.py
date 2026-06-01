"""Streaming Markdown helpers for the terminal shell."""

from __future__ import annotations

from typing import TextIO

from allCode.tui.streaming import MarkdownStreamBuffer


class MarkdownStreamPrinter:
    """Small streaming renderer for common Markdown prefixes."""

    def __init__(self, stream: TextIO, *, enabled: bool) -> None:
        self.stream = stream
        self.enabled = enabled
        self._line_start = True
        self._prefix_buffer = ""
        self._in_code = False
        self._line_style_open = False
        self._buffer = MarkdownStreamBuffer()

    def reset(self) -> None:
        self._line_start = True
        self._prefix_buffer = ""
        self._in_code = False
        self._line_style_open = False
        self._buffer.reset()

    def write(self, text: str) -> None:
        visible_text = self._buffer.append(text)
        for char in visible_text:
            self._write_char(char)
        if visible_text:
            self.stream.flush()

    def finish(self) -> None:
        visible_text = self._buffer.flush()
        for char in visible_text:
            self._write_char(char)
        if self._prefix_buffer:
            self._raw(self._prefix_buffer)
            self._prefix_buffer = ""
        if self._line_style_open and self.enabled:
            self._raw("\x1b[0m")
        self._line_style_open = False
        self._raw("\n")
        self.stream.flush()

    def _write_char(self, char: str) -> None:
        if self._line_start:
            self._buffer_prefix(char)
            return
        self._raw(char)
        if char == "\n":
            self._close_line_style()
            self._line_start = True

    def _buffer_prefix(self, char: str) -> None:
        self._prefix_buffer += char
        prefix = self._prefix_buffer
        if prefix == "\n":
            self._raw("\n")
            self._prefix_buffer = ""
            return
        if self._in_code:
            if prefix.startswith("```") and len(prefix) >= 3:
                self._in_code = False
                self._raw("```")
                self._prefix_buffer = ""
                self._line_start = False
                return
            if "```".startswith(prefix):
                return
            self._raw(prefix)
            self._prefix_buffer = ""
            self._line_start = False
            return
        if prefix.startswith("```") and len(prefix) >= 3:
            self._in_code = not self._in_code
            self._raw("```")
            self._prefix_buffer = ""
            self._line_start = False
            return
        if "```".startswith(prefix):
            return
        if prefix in {"#", "##", "###", "-", "*"} or prefix.isdigit():
            return
        if prefix.startswith(("# ", "## ", "### ")):
            self._open_style("\x1b[1;38;2;231;231;231m")
            self._prefix_buffer = ""
            self._line_start = False
            return
        if prefix in {"- ", "* "}:
            self._raw("• ")
            self._prefix_buffer = ""
            self._line_start = False
            return
        if len(prefix) >= 2 and prefix[:-1].isdigit() and prefix[-1] == ".":
            return
        if len(prefix) >= 3 and prefix[:-2].isdigit() and prefix[-2:] == ". ":
            self._raw(prefix)
            self._prefix_buffer = ""
            self._line_start = False
            return
        self._raw(prefix)
        self._prefix_buffer = ""
        self._line_start = False

    def _open_style(self, code: str) -> None:
        if self.enabled:
            self._raw(code)
            self._line_style_open = True

    def _close_line_style(self) -> None:
        if self._line_style_open and self.enabled:
            self._raw("\x1b[0m")
        self._line_style_open = False

    def _raw(self, text: str) -> None:
        self.stream.write(text)

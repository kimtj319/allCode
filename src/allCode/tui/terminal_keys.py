"""Keyboard sequence parsing for the terminal composer."""

from __future__ import annotations

import codecs
import os
import select
import termios
import tty
from contextlib import contextmanager
from typing import Iterator, TextIO

from allCode.tui.terminal_paste_sanitizer import normalize_pasted_text


class TerminalKeyReader:
    """Translate raw terminal bytes into editor actions.

    On a real terminal, input is read straight from the file descriptor with
    ``os.read`` (not the buffered text stream): an escape burst like ``ESC [ A``
    arrives together, is decoded, and the trailing ``[A`` is held in a pushback
    buffer. Escape-continuation checks consult that pushback first, so arrow keys
    are parsed instead of leaking ``[A`` as literal text. A text fallback keeps
    StringIO-based tests working.
    """

    def __init__(self, stdin: TextIO) -> None:
        self.stdin = stdin
        self._pushback = ""
        self._fd: int | None = None
        self._decoder: codecs.IncrementalDecoder | None = None
        try:
            fd = stdin.fileno()
            os.fstat(fd)
        except Exception:
            fd = None
        if fd is not None:
            self._fd = fd
            self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def _read_char(self, *, blocking: bool = True) -> str:
        if self._pushback:
            char, self._pushback = self._pushback[0], self._pushback[1:]
            return char
        if self._fd is None:
            return self.stdin.read(1)
        if not blocking:
            ready, _, _ = select.select([self._fd], [], [], 0)
            if not ready:
                return ""
        while True:
            try:
                data = os.read(self._fd, 1024)
            except OSError:
                return ""
            if not data:
                return ""
            assert self._decoder is not None
            text = self._decoder.decode(data)
            if text:
                char, self._pushback = text[0], text[1:]
                return char

    def _more_available(self, timeout: float) -> bool:
        if self._pushback:
            return True
        if self._fd is None:
            char = self.stdin.read(1)
            if char == "":
                return False
            self._pushback = char + self._pushback
            return True
        try:
            ready, _, _ = select.select([self._fd], [], [], timeout)
            return bool(ready)
        except (OSError, ValueError):
            return False

    def read_key(self) -> str:
        char = self._read_char()
        if char == "":
            raise EOFError
        if char == "\x1b":
            return self._read_escape_sequence()
        controls = {
            "\x01": "home",
            "\x03": "ctrl_c",
            "\x04": "ctrl_d",
            "\x05": "end",
            "\x0b": "ctrl_k",
            "\x0c": "redraw",
            "\x12": "redo",
            "\x15": "ctrl_u",
            "\x17": "ctrl_w",
            "\x19": "ctrl_y",
            "\x1a": "undo",
            "\x7f": "backspace",
            "\t": "tab",
            "\r": "enter",
            "\n": "newline",
        }
        return controls.get(char, char)

    def can_use_raw_mode(self) -> bool:
        fileno = getattr(self.stdin, "fileno", None)
        if fileno is None:
            return False
        try:
            termios.tcgetattr(fileno())
            return True
        except (OSError, termios.error, ValueError, AttributeError):
            return False

    @contextmanager
    def raw_mode(self, stdout: TextIO) -> Iterator[None]:
        fd = self.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            stdout.write("\x1b[?2004h")
            stdout.flush()
            yield
        finally:
            stdout.write("\x1b[?2004l")
            stdout.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _read_escape_sequence(self) -> str:
        if not self._more_available(0.05):
            return "escape"
        second = self._read_char()
        if second in {"\r", "\n"}:
            return "alt_enter"
        if second in {"b", "B"}:
            return "alt_left"
        if second in {"f", "F"}:
            return "alt_right"
        if second != "[":
            return second
        sequence = ""
        while True:
            char = self._read_char()
            if char == "":
                return "escape"
            sequence += char
            if char.isalpha() or char == "~":
                break
        if sequence == "200~":
            return "paste:" + self._read_bracketed_paste()
        return {
            "A": "up",
            "B": "down",
            "C": "right",
            "D": "left",
            "H": "home",
            "F": "end",
            "1~": "home",
            "3~": "delete",
            "4~": "end",
        }.get(sequence, "escape")

    def _read_bracketed_paste(self) -> str:
        buffer = ""
        end = "\x1b[201~"
        while True:
            char = self._read_char()
            if char == "":
                return normalize_pasted_text(buffer)
            buffer += char
            if buffer.endswith(end):
                return normalize_pasted_text(buffer[: -len(end)])

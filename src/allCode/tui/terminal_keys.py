"""Keyboard sequence parsing for the terminal composer."""

from __future__ import annotations

import select
import termios
import tty
from contextlib import contextmanager
from typing import Iterator, TextIO


class TerminalKeyReader:
    """Translate raw terminal bytes into editor actions."""

    def __init__(self, stdin: TextIO) -> None:
        self.stdin = stdin

    def read_key(self) -> str:
        char = self.stdin.read(1)
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
        if not self._input_ready(0.02):
            return "escape"
        second = self.stdin.read(1)
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
            char = self.stdin.read(1)
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
            char = self.stdin.read(1)
            if char == "":
                return buffer
            buffer += char
            if buffer.endswith(end):
                return buffer[: -len(end)]

    def _input_ready(self, timeout: float) -> bool:
        try:
            readable, _, _ = select.select([self.stdin], [], [], timeout)
            return bool(readable)
        except (OSError, ValueError):
            return False

"""Declarative keymap for the terminal composer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CommandName = Literal[
    "insert_char",
    "insert_newline",
    "submit",
    "cancel_or_interrupt",
    "eof_or_delete_forward",
    "delete_backward",
    "delete_forward",
    "delete_backward_word",
    "move_left",
    "move_right",
    "move_word_left",
    "move_word_right",
    "move_up",
    "move_down",
    "move_line_start",
    "move_line_end",
    "kill_line_start",
    "kill_line_end",
    "yank",
    "undo",
    "redo",
    "complete_or_queue",
    "paste",
    "redraw",
    "noop",
]


@dataclass(frozen=True)
class EditorCommand:
    name: CommandName
    text: str = ""


class TerminalKeymap:
    """Translate parsed key names into editor commands."""

    _bindings: dict[str, CommandName] = {
        "ctrl_c": "cancel_or_interrupt",
        "ctrl_d": "eof_or_delete_forward",
        "enter": "submit",
        "newline": "submit",
        "alt_enter": "insert_newline",
        "backspace": "delete_backward",
        "delete": "delete_forward",
        "left": "move_left",
        "right": "move_right",
        "alt_left": "move_word_left",
        "alt_right": "move_word_right",
        "up": "move_up",
        "down": "move_down",
        "home": "move_line_start",
        "end": "move_line_end",
        "ctrl_u": "kill_line_start",
        "ctrl_k": "kill_line_end",
        "ctrl_y": "yank",
        "ctrl_w": "delete_backward_word",
        "undo": "undo",
        "redo": "redo",
        "tab": "complete_or_queue",
        "redraw": "redraw",
        "escape": "noop",
    }

    def resolve(self, key: str) -> EditorCommand:
        if key.startswith("paste:"):
            return EditorCommand(name="paste", text=key.removeprefix("paste:"))
        if key in self._bindings:
            return EditorCommand(name=self._bindings[key])
        if len(key) == 1 and key.isprintable():
            return EditorCommand(name="insert_char", text=key)
        return EditorCommand(name="noop")

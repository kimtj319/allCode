"""Editable terminal text buffer used by the Codex-style composer."""

from __future__ import annotations

from dataclasses import dataclass

from allCode.tui.terminal_elements import ElementKind, TextElement, TextElementSnapshot, TextRange


WORD_SEPARATORS = "`~!@#$%^&*()-=+[{]}\\|;:'\",.<>/?"


@dataclass
class CursorPosition:
    line: int
    column: int


@dataclass(frozen=True)
class _AreaSnapshot:
    text: str
    cursor: int
    elements: tuple[TextElementSnapshot, ...]
    next_element_id: int


class TerminalTextArea:
    """Small multiline editor model with cursor movement and a kill buffer."""

    def __init__(self, text: str = "") -> None:
        self._text = text
        self._cursor = len(text)
        self._kill_buffer = ""
        self._preferred_column: int | None = None
        self._undo_stack: list[_AreaSnapshot] = []
        self._redo_stack: list[_AreaSnapshot] = []
        self._elements: list[TextElement] = []
        self._next_element_id = 1

    @property
    def text(self) -> str:
        return self._text

    @property
    def cursor(self) -> int:
        return self._cursor

    def set_cursor(self, index: int) -> None:
        self._cursor = self._clamp(index)
        self._preferred_column = None

    def set_text(self, text: str, *, cursor: int | None = None) -> None:
        self._snapshot()
        self._text = text
        self._cursor = self._clamp(cursor if cursor is not None else len(text))
        self._preferred_column = None
        self._elements.clear()

    def insert(self, value: str) -> None:
        if not value:
            return
        self._snapshot()
        self._shift_elements_for_insert(self._cursor, len(value))
        self._text = self._text[: self._cursor] + value + self._text[self._cursor :]
        self._cursor += len(value)
        self._preferred_column = None

    def insert_element(self, label: str, *, kind: ElementKind) -> int:
        if not label:
            return 0
        self._snapshot()
        start = self._cursor
        self._shift_elements_for_insert(start, len(label))
        self._text = self._text[:start] + label + self._text[start:]
        self._cursor = start + len(label)
        element_id = self._next_element_id
        self._next_element_id += 1
        self._elements.append(TextElement(id=element_id, range=TextRange(start=start, end=self._cursor), kind=kind, label=label))
        self._elements.sort(key=lambda element: element.range.start)
        self._preferred_column = None
        return element_id

    def delete_backward(self) -> None:
        if self._cursor == 0:
            return
        element = self._element_ending_at(self._cursor) or self._element_containing(self._cursor - 1)
        if element is not None:
            self._delete_range(element.range.start, element.range.end)
            return
        self._snapshot()
        self._delete_range_raw(self._cursor - 1, self._cursor, cursor=self._cursor - 1)
        self._preferred_column = None

    def delete_forward(self) -> None:
        if self._cursor >= len(self._text):
            return
        element = self._element_starting_at(self._cursor) or self._element_containing(self._cursor)
        if element is not None:
            self._delete_range(element.range.start, element.range.end)
            return
        self._snapshot()
        self._delete_range_raw(self._cursor, self._cursor + 1, cursor=self._cursor)
        self._preferred_column = None

    def delete_backward_word(self) -> None:
        start = self._beginning_of_previous_word()
        if start == self._cursor:
            return
        self._snapshot()
        self._kill_buffer = self._text[start : self._cursor]
        self._delete_range_raw(start, self._cursor, cursor=start)
        self._preferred_column = None

    def kill_to_line_start(self) -> None:
        start = self._line_start(self._cursor)
        if start == self._cursor:
            return
        self._snapshot()
        self._kill_buffer = self._text[start : self._cursor]
        self._delete_range_raw(start, self._cursor, cursor=start)
        self._preferred_column = None

    def kill_to_line_end(self) -> None:
        end = self._line_end(self._cursor)
        if end == self._cursor and end < len(self._text) and self._text[end] == "\n":
            end += 1
        if end == self._cursor:
            return
        self._snapshot()
        self._kill_buffer = self._text[self._cursor : end]
        self._delete_range_raw(self._cursor, end, cursor=self._cursor)
        self._preferred_column = None

    def yank(self) -> None:
        self.insert(self._kill_buffer)

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self._make_snapshot())
        self._restore_snapshot(self._undo_stack.pop())
        self._preferred_column = None
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._make_snapshot())
        self._restore_snapshot(self._redo_stack.pop())
        self._preferred_column = None
        return True

    def move_left(self) -> None:
        element = self._element_ending_at(self._cursor)
        self._cursor = element.range.start if element is not None else self._clamp_left(self._cursor - 1)
        self._preferred_column = None

    def move_right(self) -> None:
        element = self._element_starting_at(self._cursor)
        self._cursor = element.range.end if element is not None else self._clamp_right(self._cursor + 1)
        self._preferred_column = None

    def move_word_left(self) -> None:
        self._cursor = self._beginning_of_previous_word()
        self._preferred_column = None

    def move_word_right(self) -> None:
        self._cursor = self._end_of_next_word()
        self._preferred_column = None

    def move_line_start(self) -> None:
        self._cursor = self._line_start(self._cursor)
        self._preferred_column = None

    def move_line_end(self) -> None:
        self._cursor = self._line_end(self._cursor)
        self._preferred_column = None

    def move_up(self) -> bool:
        position = self.cursor_position()
        if position.line == 0:
            return False
        column = self._preferred_column if self._preferred_column is not None else position.column
        self._preferred_column = column
        self._cursor = self._index_for_line_column(position.line - 1, column)
        return True

    def move_down(self) -> bool:
        position = self.cursor_position()
        lines = self.lines()
        if position.line >= len(lines) - 1:
            return False
        column = self._preferred_column if self._preferred_column is not None else position.column
        self._preferred_column = column
        self._cursor = self._index_for_line_column(position.line + 1, column)
        return True

    def cursor_position(self) -> CursorPosition:
        before = self._text[: self._cursor]
        line = before.count("\n")
        last_break = before.rfind("\n")
        column = len(before) if last_break == -1 else len(before) - last_break - 1
        return CursorPosition(line=line, column=column)

    def is_cursor_on_first_line(self) -> bool:
        return self.cursor_position().line == 0

    def is_cursor_on_last_line(self) -> bool:
        return self.cursor_position().line == len(self.lines()) - 1

    def lines(self) -> list[str]:
        return self._text.split("\n")

    def element_snapshots(self) -> list[TextElementSnapshot]:
        return [
            TextElementSnapshot(
                id=element.id,
                start=element.range.start,
                end=element.range.end,
                kind=element.kind,
                label=element.label,
            )
            for element in self._elements
        ]

    def element_labels(self, *, kind: ElementKind | None = None) -> list[str]:
        return [element.label for element in self._elements if kind is None or element.kind == kind]

    def _beginning_of_previous_word(self) -> int:
        index = self._cursor
        while index > 0 and self._text[index - 1].isspace():
            index -= 1
        while index > 0 and not self._text[index - 1].isspace() and self._text[index - 1] not in WORD_SEPARATORS:
            index -= 1
        return index

    def _end_of_next_word(self) -> int:
        index = self._cursor
        text_len = len(self._text)
        while index < text_len and self._text[index].isspace():
            index += 1
        while index < text_len and not self._text[index].isspace() and self._text[index] not in WORD_SEPARATORS:
            index += 1
        return index

    def _line_start(self, index: int) -> int:
        return self._text.rfind("\n", 0, index) + 1

    def _line_end(self, index: int) -> int:
        end = self._text.find("\n", index)
        return len(self._text) if end == -1 else end

    def _index_for_line_column(self, line: int, column: int) -> int:
        lines = self.lines()
        line = max(0, min(line, len(lines) - 1))
        offset = sum(len(lines[index]) + 1 for index in range(line))
        return offset + min(column, len(lines[line]))

    def _clamp(self, index: int) -> int:
        return self._clamp_outside_element(max(0, min(index, len(self._text))))

    def _clamp_raw(self, index: int) -> int:
        return max(0, min(index, len(self._text)))

    def _snapshot(self) -> None:
        state = self._make_snapshot()
        if self._undo_stack and self._undo_stack[-1] == state:
            return
        self._undo_stack.append(state)
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _make_snapshot(self) -> _AreaSnapshot:
        return _AreaSnapshot(
            text=self._text,
            cursor=self._cursor,
            elements=tuple(self.element_snapshots()),
            next_element_id=self._next_element_id,
        )

    def _restore_snapshot(self, snapshot: _AreaSnapshot) -> None:
        self._text = snapshot.text
        self._cursor = self._clamp_raw(snapshot.cursor)
        self._next_element_id = snapshot.next_element_id
        self._elements = [
            TextElement(
                id=element.id,
                range=TextRange(start=element.start, end=element.end),
                kind=element.kind,
                label=element.label,
            )
            for element in snapshot.elements
        ]

    def _delete_range(self, start: int, end: int) -> None:
        self._snapshot()
        self._delete_range_raw(start, end, cursor=start)
        self._preferred_column = None

    def _delete_range_raw(self, start: int, end: int, *, cursor: int) -> None:
        start, end = self._expand_range_to_element_boundaries(start, end)
        removed = end - start
        self._text = self._text[:start] + self._text[end:]
        self._elements = [element for element in self._elements if not element.range.overlaps(start, end)]
        for element in self._elements:
            if element.range.start >= end:
                element.range.start -= removed
                element.range.end -= removed
        self._cursor = self._clamp(cursor)

    def _shift_elements_for_insert(self, index: int, length: int) -> None:
        for element in self._elements:
            if element.range.start >= index:
                element.range.start += length
                element.range.end += length
            elif element.range.contains(index):
                element.range.end += length

    def _expand_range_to_element_boundaries(self, start: int, end: int) -> tuple[int, int]:
        expanded_start = start
        expanded_end = end
        changed = True
        while changed:
            changed = False
            for element in self._elements:
                if element.range.overlaps(expanded_start, expanded_end):
                    new_start = min(expanded_start, element.range.start)
                    new_end = max(expanded_end, element.range.end)
                    changed = changed or new_start != expanded_start or new_end != expanded_end
                    expanded_start, expanded_end = new_start, new_end
        return expanded_start, expanded_end

    def _element_ending_at(self, index: int) -> TextElement | None:
        return next((element for element in self._elements if element.range.end == index), None)

    def _element_starting_at(self, index: int) -> TextElement | None:
        return next((element for element in self._elements if element.range.start == index), None)

    def _element_containing(self, index: int) -> TextElement | None:
        return next((element for element in self._elements if element.range.start <= index < element.range.end), None)

    def _clamp_outside_element(self, index: int) -> int:
        element = self._element_containing(index)
        if element is None:
            return index
        before_distance = abs(index - element.range.start)
        after_distance = abs(element.range.end - index)
        return element.range.start if before_distance <= after_distance else element.range.end

    def _clamp_left(self, index: int) -> int:
        element = self._element_containing(index)
        return element.range.start if element is not None else max(0, min(index, len(self._text)))

    def _clamp_right(self, index: int) -> int:
        element = self._element_containing(index)
        return element.range.end if element is not None else max(0, min(index, len(self._text)))

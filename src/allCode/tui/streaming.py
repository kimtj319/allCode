"""Streaming Markdown helpers for TUI transcript rendering."""

from __future__ import annotations


class MarkdownStreamBuffer:
    """Streams normal text while buffering Markdown tables until they are complete."""

    def __init__(self) -> None:
        self.mode = "normal"
        self.line_start = True
        self.prefix = ""
        self.current_line = ""
        self.header_line = ""
        self.table_lines: list[str] = []

    def append(self, delta: str) -> str:
        output: list[str] = []
        for char in delta:
            if self.mode == "normal":
                self._append_normal_char(char, output)
            else:
                self.current_line += char
                if char == "\n":
                    self._finish_buffered_line(output)
        return "".join(output)

    def flush(self) -> str:
        output: list[str] = []
        if self.mode == "normal":
            output.append(self.prefix)
        elif self.mode == "candidate_header":
            output.append(self.current_line)
        elif self.mode == "await_separator":
            output.extend([self.header_line, self.current_line])
        elif self.mode == "table":
            output.extend(self.table_lines)
            output.append(self.current_line)
        self.reset()
        return "".join(output)

    def reset(self) -> None:
        self.mode = "normal"
        self.line_start = True
        self.prefix = ""
        self.current_line = ""
        self.header_line = ""
        self.table_lines = []

    def _append_normal_char(self, char: str, output: list[str]) -> None:
        if self.line_start:
            if char in {" ", "\t"}:
                self.prefix += char
                return
            if char == "|":
                self.current_line = self.prefix + char
                self.prefix = ""
                self.mode = "candidate_header"
                self.line_start = False
                return
            output.append(self.prefix + char)
            self.prefix = ""
            self.line_start = char == "\n"
            return
        output.append(char)
        if char == "\n":
            self.line_start = True

    def _finish_buffered_line(self, output: list[str]) -> None:
        line = self.current_line
        self.current_line = ""
        if self.mode == "candidate_header":
            self.header_line = line
            self.mode = "await_separator"
            return
        if self.mode == "await_separator":
            if _is_table_separator(line):
                self.table_lines = [self.header_line, line]
                self.header_line = ""
                self.mode = "table"
                return
            output.append(self.header_line)
            self.header_line = ""
            if _starts_table_line(line):
                self.header_line = line
                self.mode = "await_separator"
                return
            output.append(line)
            self.mode = "normal"
            self.line_start = True
            return
        if self.mode == "table":
            if _is_table_row(line):
                self.table_lines.append(line)
                return
            output.append("".join(self.table_lines))
            self.table_lines = []
            self.mode = "normal"
            self.line_start = True
            output.append(line)


def _starts_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    if not _is_table_row(stripped):
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return bool(cells) and all(cell and set(cell) <= {"-", ":", " "} and "-" in cell for cell in cells)

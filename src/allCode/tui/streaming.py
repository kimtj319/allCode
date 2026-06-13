"""Streaming Markdown helpers for TUI transcript rendering."""

from __future__ import annotations

import re


class MarkdownStreamBuffer:
    """Buffer model deltas into readable text units and complete Markdown tables."""

    def __init__(self) -> None:
        self.mode = "normal"
        self.line_start = True
        self.prefix = ""
        self.text_buffer = ""
        self.current_line = ""
        self.header_line = ""
        self.table_lines: list[str] = []
        self.code_lines: list[str] = []

    def append(self, delta: str) -> str:
        output: list[str] = []
        for char in delta:
            if self.mode == "normal":
                self._append_normal_char(char, output)
            else:
                if self.mode == "table" and self._table_has_ended_before(char):
                    output.append("".join(self.table_lines))
                    self.table_lines = []
                    self.mode = "normal"
                    self.line_start = True
                    self._append_normal_char(char, output)
                    continue
                self.current_line += char
                if char == "\n":
                    self._finish_buffered_line(output)
        return "".join(output)

    def flush(self) -> str:
        output: list[str] = []
        if self.mode == "normal":
            output.append(self.text_buffer)
            output.append(self.prefix)
        elif self.mode == "candidate_header":
            output.append(self.current_line)
        elif self.mode == "await_separator":
            output.extend([self.header_line, self.current_line])
        elif self.mode == "table":
            output.extend(self.table_lines)
            output.append(self.current_line)
        elif self.mode in {"code", "code_candidate"}:
            output.extend(self.code_lines)
            output.append(self.current_line)
        elif self.mode == "block_line":
            output.append(self.current_line)
        self.reset()
        return "".join(output)

    def reset(self) -> None:
        self.mode = "normal"
        self.line_start = True
        self.prefix = ""
        self.text_buffer = ""
        self.current_line = ""
        self.header_line = ""
        self.table_lines = []
        self.code_lines = []

    def _append_normal_char(self, char: str, output: list[str]) -> None:
        if self.line_start:
            if char in {" ", "\t"}:
                self.prefix += char
                return
            if char == "|":
                self._flush_text(output)
                self.current_line = self.prefix + char
                self.prefix = ""
                self.mode = "candidate_header"
                self.line_start = False
                return
            if char == "`":
                # Hold a line that begins with a backtick: it may open a fenced
                # code block, which must be rendered as one whole block instead of
                # fragmented per streamed line.
                self._flush_text(output)
                self.current_line = self.prefix + char
                self.prefix = ""
                self.mode = "code_candidate"
                self.line_start = False
                return
            if char in {"#", ">"}:
                # Hold a heading/blockquote line until its newline so a mid-line
                # sentence boundary cannot split it and drop the block prefix.
                self._flush_text(output)
                self.current_line = self.prefix + char
                self.prefix = ""
                self.mode = "block_line"
                self.line_start = False
                return
            self.text_buffer += self.prefix + char
            self.prefix = ""
            self.line_start = char == "\n"
            if _should_flush_text(self.text_buffer):
                self._flush_text(output)
            return
        self.text_buffer += char
        if char == "\n":
            self.line_start = True
        if _should_flush_text(self.text_buffer):
            self._flush_text(output)

    def _finish_buffered_line(self, output: list[str]) -> None:
        line = self.current_line
        self.current_line = ""
        if self.mode == "block_line":
            output.append(line)
            self.mode = "normal"
            self.line_start = True
            return
        if self.mode == "code_candidate":
            if _is_code_fence(line):
                self.code_lines = [line]
                self.mode = "code"
                return
            # Not a fence (e.g. an inline-code span starting the line); emit as text.
            output.append(line)
            self.mode = "normal"
            self.line_start = True
            return
        if self.mode == "code":
            self.code_lines.append(line)
            if _is_code_fence(line):
                output.append("".join(self.code_lines))
                self.code_lines = []
                self.mode = "normal"
                self.line_start = True
            return
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

    def _flush_text(self, output: list[str]) -> None:
        if self.text_buffer:
            output.append(self.text_buffer)
            self.text_buffer = ""

    def _table_has_ended_before(self, char: str) -> bool:
        candidate = self.current_line + char
        stripped = candidate.lstrip()
        return bool(stripped) and not stripped.startswith("|")


def _starts_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_code_fence(line: str) -> bool:
    return line.lstrip().startswith("```")


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    if not _is_table_row(stripped):
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return bool(cells) and all(cell and set(cell) <= {"-", ":", " "} and "-" in cell for cell in cells)


_STRONG_SENTENCE_BOUNDARIES = {"?", "!", "。", "？", "！", "…"}
_URL_OR_DOMAIN_RE = re.compile(r"(://|www\.|[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")


def _should_flush_text(text: str) -> bool:
    if not text:
        return False
    if text.endswith("\n"):
        return True
    last = text[-1]
    if last in _STRONG_SENTENCE_BOUNDARIES:
        return True
    if last == ".":
        return not _dot_is_part_of_continuing_token(text, immediate=True)
    if last.isspace():
        stripped = text.rstrip()
        if not stripped:
            return False
        previous = stripped[-1]
        if previous in _STRONG_SENTENCE_BOUNDARIES:
            return True
        if previous == ".":
            return not _dot_is_part_of_continuing_token(stripped, immediate=False)
    return False


def _dot_is_part_of_continuing_token(text: str, *, immediate: bool) -> bool:
    stripped = text.rstrip()
    if not stripped.endswith("."):
        return False
    token = stripped.split()[-1].rstrip(")]}>,;:")
    if not token.endswith("."):
        return False
    prefix = token[:-1]
    if not prefix:
        return False
    if immediate and prefix[-1].isdigit():
        return True
    if _token_is_numbered_markdown_marker(stripped, token):
        return True
    if "://" in prefix or prefix.startswith("www."):
        return True
    if prefix.isascii() and _URL_OR_DOMAIN_RE.search(prefix):
        return True
    if immediate and prefix[-1].isascii() and prefix[-1].isalpha():
        return True
    return False


def _token_is_numbered_markdown_marker(text: str, token: str) -> bool:
    number = token[:-1].strip("*_`~")
    if not number.isdigit():
        return False
    line = text.rsplit("\n", 1)[-1]
    before_token = line[: max(0, len(line) - len(token))].strip()
    if not before_token:
        return True
    markdown_prefix = before_token.strip("*_`~ ")
    return markdown_prefix in {"#", "##", "###", "####", "#####", "######", "-", "*", "+", ">", "> -", "> *", "> +"}

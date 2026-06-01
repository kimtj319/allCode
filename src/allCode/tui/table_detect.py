"""Small Markdown table detection helpers."""

from __future__ import annotations


def has_markdown_table(source: str) -> bool:
    lines = source.splitlines()
    for index in range(len(lines) - 1):
        if _is_table_row(lines[index]) and _is_table_separator(lines[index + 1]):
            return True
    return False


def table_holdback_start(source: str) -> int | None:
    """Return the byte offset where a trailing table candidate should be held."""

    line_start = 0
    previous_start = 0
    previous_line = ""
    for line in source.splitlines(keepends=True):
        stripped_line = line.rstrip("\r\n")
        if _is_table_separator(stripped_line) and _is_table_row(previous_line):
            return previous_start
        previous_start = line_start
        previous_line = stripped_line
        line_start += len(line)
    if _is_table_row(previous_line):
        return previous_start
    return None


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _is_table_separator(line: str) -> bool:
    if not _is_table_row(line):
        return False
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(cell and "-" in cell and set(cell) <= {"-", ":", " "} for cell in cells)

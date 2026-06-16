"""Compact Markdown block rendering for the terminal-native UI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from rich import box
from rich.console import Console, RenderableType
from rich.markdown import Markdown
from rich.style import Style
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from allCode.tui.terminal_width import display_width

# Map common fence labels to Pygments lexer names so syntax highlighting works
# for the languages assistants emit most. Unknown labels fall back to plain text.
_SYNTAX_LANGUAGE_ALIASES = {
    "yml": "yaml",
    "dockerfile": "docker",
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "console": "bash",
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "jsx": "javascript",
    "rs": "rust",
    "yaml": "yaml",
    "json": "json",
    "toml": "toml",
    "ini": "ini",
    "python": "python",
    "bash": "bash",
    "go": "go",
    "sql": "sql",
    "html": "html",
    "css": "css",
}

_SYNTAX_PLAIN_LABELS = {"", "text", "txt", "plain", "plaintext", "none", "output", "log"}

# Codex-style table: no outer/vertical borders, a segmented heavy rule under the
# header, and a light rule between each row (gaps at column boundaries).
_CODEX_TABLE_BOX = box.Box(
    "    \n"  # top
    "    \n"  # head
    " ━  \n"  # head_row (heavy, gap at column junctions)
    "    \n"  # mid
    " ─  \n"  # row (light separator between data rows)
    " ─  \n"  # foot_row
    "    \n"  # foot
    "    \n"  # bottom
)

_FENCE_START_RE = re.compile(r"^```([A-Za-z0-9_+.-]*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_UNORDERED_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
# Inline spans, longest/most-specific first. The italic alternative is
# flanking-aware ("*" must hug the word on the inside and be bounded by a
# non-word, non-"*" char on the outside) so literal asterisks in code/math such
# as ``n*log`` or ``2*3`` are not swallowed as emphasis and dropped.
_INLINE_RE = re.compile(
    r"(\[[^\]\n]+\]\([^)\s]+\)"
    r"|\*\*[^*\n]+\*\*"
    r"|`[^`\n]+`"
    r"|(?<![\w*])\*(?!\s)[^*\n]+?(?<!\s)\*)"
)
_LINK_RE = re.compile(r"^\[([^\]\n]+)\]\(([^)\s]+)\)$")


@dataclass(frozen=True)
class MarkdownBlock:
    kind: str
    lines: list[str]
    language: str = ""


def render_compact_markdown(
    console: Console,
    source: str,
    *,
    emitted: bool = False,
    last_offset: bool = False,
) -> tuple[bool, bool]:
    """Render common Markdown blocks with Codex-like, restrained block spacing.

    Block-level elements (code, table, quote, heading) get one blank line of
    breathing room; paragraphs and lists stay tight. ``emitted``/``last_offset``
    carry state across streamed chunks so spacing is consistent without inserting
    spurious breaks inside a paragraph that streamed in pieces.
    """

    local_first = True
    for block in _parse_blocks(source):
        space_after = block.kind in {"code", "table", "quote"}
        # Within one render call, separate consecutive blocks with a blank line to
        # restore the source's vertical rhythm. Across streamed chunks (local_first
        # on a fresh call) only offset blocks get a leading blank, so a paragraph
        # that streamed in pieces is never split by a spurious blank.
        offset_before = block.kind in {"code", "table", "quote", "heading"} and emitted
        if (not local_first or offset_before) and not last_offset:
            console.print()
        _render_block(console, block)
        if space_after:
            console.print()
        last_offset = space_after
        emitted = True
        local_first = False
    return emitted, last_offset


def _render_block(console: Console, block: MarkdownBlock) -> None:
    try:
        if block.kind == "code":
            _render_code(console, block)
        elif block.kind == "table":
            _render_table(console, block.lines)
        elif block.kind == "quote":
            _render_quote(console, block.lines)
        elif block.kind == "heading":
            _render_heading(console, block.lines[0])
        elif block.kind == "list":
            _render_list(console, block.lines)
        else:
            _print_renderable_compact(console, Markdown(_escape_intraword_asterisks("\n".join(block.lines))))
    except Exception:
        _print_renderable_compact(console, Markdown("\n".join(block.lines)))


def _escape_intraword_asterisks(text: str) -> str:
    """Escape single ``*`` characters that sit between word characters (e.g.
    ``n*log``, ``2*3``, ``a*b``). Rich's Markdown treats these as intraword
    emphasis and silently deletes the asterisks together with the surrounding
    text run; escaping them keeps the literal multiplication/glob/regex text.
    Inline code spans are left untouched so backslashes do not appear in them."""

    parts = re.split(r"(`[^`\n]+`)", text)
    for index, part in enumerate(parts):
        if part.startswith("`") and part.endswith("`"):
            continue
        parts[index] = re.sub(r"(?<=\w)\*(?=\w)", r"\\*", part)
    return "".join(parts)


def _parse_blocks(source: str) -> list[MarkdownBlock]:
    lines = source.splitlines()
    blocks: list[MarkdownBlock] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        fence_match = _FENCE_START_RE.match(line.strip())
        if fence_match:
            block, index = _consume_code_block(lines, index, fence_match.group(1))
            blocks.append(block)
            continue
        if _is_table_start(lines, index):
            block, index = _consume_table(lines, index)
            blocks.append(block)
            continue
        if _is_quote_line(line):
            block, index = _consume_quote(lines, index)
            blocks.append(block)
            continue
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            blocks.append(MarkdownBlock(kind="heading", lines=[heading_match.group(2)]))
            index += 1
            continue
        if _is_list_line(line):
            block, index = _consume_list(lines, index)
            blocks.append(block)
            continue
        block, index = _consume_generic(lines, index)
        blocks.append(block)
    return blocks


def _is_list_line(line: str) -> bool:
    return bool(_ORDERED_RE.match(line) or _UNORDERED_RE.match(line))


def _consume_list(lines: list[str], start: int) -> tuple[MarkdownBlock, int]:
    items: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            break
        if _is_list_line(line):
            items.append(line)
            index += 1
            continue
        # Lazy continuation: a non-blank line that does not start a new block
        # belongs to the previous item. This reabsorbs stray fragments the model
        # puts on their own line (e.g. a closing quotation mark after "...?"),
        # which would otherwise render as an orphaned line at the left margin.
        if items and not _starts_new_block(lines, index):
            items[-1] = items[-1].rstrip() + " " + line.strip()
            index += 1
            continue
        break
    return MarkdownBlock(kind="list", lines=items), index


def _starts_new_block(lines: list[str], index: int) -> bool:
    line = lines[index]
    stripped = line.strip()
    if _FENCE_START_RE.match(stripped) or _HEADING_RE.match(line) or _is_quote_line(line):
        return True
    return _is_table_start(lines, index)


def _consume_code_block(lines: list[str], start: int, language: str) -> tuple[MarkdownBlock, int]:
    body: list[str] = []
    index = start + 1
    while index < len(lines):
        if lines[index].strip() == "```":
            return MarkdownBlock(kind="code", lines=body, language=language.strip()), index + 1
        body.append(lines[index])
        index += 1
    return MarkdownBlock(kind="code", lines=body, language=language.strip()), index


def _consume_table(lines: list[str], start: int) -> tuple[MarkdownBlock, int]:
    table_lines = [lines[start], lines[start + 1]]
    index = start + 2
    while index < len(lines) and _is_table_continuation(lines[index], table_lines[-1]):
        table_lines.append(lines[index])
        index += 1
    return MarkdownBlock(kind="table", lines=table_lines), index


def _consume_quote(lines: list[str], start: int) -> tuple[MarkdownBlock, int]:
    quote_lines: list[str] = []
    index = start
    while index < len(lines):
        if _is_quote_line(lines[index]):
            quote_lines.append(lines[index])
            index += 1
            continue
        if not lines[index].strip():
            # A blank line only stays inside the quote if another quote line
            # follows; trailing blanks end the quote (otherwise they render as a
            # stray empty "│" line).
            look = index + 1
            while look < len(lines) and not lines[look].strip():
                look += 1
            if look < len(lines) and _is_quote_line(lines[look]):
                quote_lines.append(">")
                index += 1
                continue
        break
    return MarkdownBlock(kind="quote", lines=quote_lines), index


def _consume_generic(lines: list[str], start: int) -> tuple[MarkdownBlock, int]:
    block_lines: list[str] = []
    index = start
    while index < len(lines):
        if not lines[index].strip():
            break
        if block_lines and (
            _FENCE_START_RE.match(lines[index].strip())
            or _is_table_start(lines, index)
            or _is_quote_line(lines[index])
            or _is_list_line(lines[index])
        ):
            break
        block_lines.append(lines[index])
        index += 1
    return MarkdownBlock(kind="generic", lines=block_lines), index


def _render_code(console: Console, block: MarkdownBlock) -> None:
    code = "\n".join(block.lines).rstrip("\n")
    if not code:
        return
    # Syntax-highlight fenced code when the fence names a known language, using a
    # terminal-palette theme with no background fill so it blends into the answer
    # body (the answer renderer adds the 2-column indent). Unknown/plain labels and
    # any highlighter error fall back to plain text.
    label = (block.language or "").strip().lower()
    if label not in _SYNTAX_PLAIN_LABELS:
        lexer = _SYNTAX_LANGUAGE_ALIASES.get(label, label)
        try:
            console.print(
                Syntax(
                    code,
                    lexer,
                    theme="ansi_dark",
                    background_color="default",
                    word_wrap=False,
                    padding=0,
                )
            )
            return
        except Exception:
            pass
    console.print(Text(code))


def _render_table(console: Console, lines: list[str]) -> None:
    if _table_is_malformed(lines):
        headers = _parse_table_row(lines[0]) if lines else []
        _render_malformed_table_fallback(console, headers, lines[2:])
        return
    rows = [_parse_table_row(line) for line in lines]
    if len(rows) < 2:
        _print_renderable_compact(console, Markdown("\n".join(lines)))
        return
    headers = rows[0]
    body_rows = [row for row in rows[2:] if any(cell.strip() for cell in row)]
    if not headers or not body_rows:
        _print_renderable_compact(console, Markdown("\n".join(lines)))
        return
    normalized_rows = [_fit_row(row, len(headers)) for row in body_rows]
    if _table_is_too_wide(headers, normalized_rows, console.width):
        _render_table_fallback(console, headers, normalized_rows)
        return
    # Codex draws a segmented heavy rule under the header and a light rule between
    # rows, with no vertical/outer borders.
    table = Table(
        box=_CODEX_TABLE_BOX,
        show_edge=False,
        show_lines=True,
        pad_edge=False,
        padding=(0, 1),
        header_style="bold",
    )
    for header in headers:
        table.add_column(_strip_inline_markup(header.strip()))
    for row in normalized_rows:
        table.add_row(*[_inline_markup(cell.strip()) for cell in row])
    console.print(table)


def _render_table_fallback(console: Console, headers: list[str], rows: list[list[str]]) -> None:
    for row in rows:
        parts = []
        for header, cell in zip(headers, row, strict=False):
            if cell.strip():
                parts.append(f"{header.strip()}: {cell.strip()}")
        if parts:
            console.print(Text("• " + " · ".join(parts)))


def _render_malformed_table_fallback(console: Console, headers: list[str], body_lines: list[str]) -> None:
    header_prefix = " / ".join(header.strip() for header in headers if header.strip())
    if header_prefix:
        console.print(Text(header_prefix, style="bold"))
    for line in _readable_lines_from_malformed_table(body_lines):
        console.print(Text("• " + line))


def _readable_lines_from_malformed_table(lines: list[str]) -> list[str]:
    text = "\n".join(lines)
    text = re.sub(r"\s*\|\s*\|\s*", "\n", text)
    readable: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        expanded = _readable_lines_from_malformed_row(line)
        for item in expanded:
            if item and not _is_separator_text(item):
                readable.append(item)
    return readable


def _readable_lines_from_malformed_row(line: str) -> list[str]:
    line = line.strip("|").strip()
    if not line or _is_separator_text(line):
        return []
    if "|" not in line:
        return [_compact_table_text(line)]

    cells = [_compact_table_text(cell) for cell in _parse_table_row(line)]
    cells = [cell for cell in cells if cell and not _is_separator_text(cell)]
    if not cells:
        return []
    if len(cells) == 1:
        return cells

    label = cells[0].rstrip(":")
    details = [cell for cell in cells[1:] if cell]
    if not details:
        return [label]
    return [f"{label}: {' · '.join(details)}"]


def _compact_table_text(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    text = re.sub(r"\s*\|\s*", " · ", text)
    text = _strip_leading_list_marker(text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text


def _strip_leading_list_marker(line: str) -> str:
    stripped = line.strip()
    for marker in ("• ", "- ", "* "):
        if stripped.startswith(marker):
            return stripped[len(marker) :].strip()
    return stripped


def _render_quote(console: Console, lines: Iterable[str]) -> None:
    for raw_line in lines:
        text = raw_line.strip()
        if text.startswith(">"):
            text = text[1:]
            if text.startswith(" "):
                text = text[1:]
        prefix = Text("│ ", style="dim")
        prefix.append_text(_inline_markup(text, base_style="dim"))
        console.print(prefix)


def _render_heading(console: Console, text: str) -> None:
    heading = _inline_markup(text.strip(), base_style="bold")
    heading.stylize("bold")
    console.print(heading)


def _render_list(console: Console, lines: list[str]) -> None:
    for line in lines:
        ordered = _ORDERED_RE.match(line)
        if ordered:
            indent, number, content = ordered.group(1), ordered.group(2), ordered.group(3)
            _print_list_item(console, indent, f"{number}. ", content)
            continue
        unordered = _UNORDERED_RE.match(line)
        if unordered:
            indent, content = unordered.group(1), unordered.group(2)
            _print_list_item(console, indent, "• ", content)
            continue
        console.print(_inline_markup(line.strip()))


def _print_list_item(console: Console, indent: str, marker: str, content: str) -> None:
    """Print a list item so wrapped continuation lines hang-indent under the item
    text instead of falling back to the left margin (which made wrapped bullets
    read as new top-level lines)."""

    body = _inline_markup(content)
    marker_width = display_width(indent) + display_width(marker)
    avail = max(1, console.width - marker_width)
    wrapped = body.wrap(console, avail)
    hang = " " * marker_width
    if not wrapped:
        console.print(Text(f"{indent}{marker}"))
        return
    for row, segment in enumerate(wrapped):
        prefix = Text(f"{indent}{marker}" if row == 0 else hang)
        prefix.append_text(segment)
        console.print(prefix)


def _strip_inline_markup(text: str) -> str:
    return _inline_markup(text).plain


def _inline_markup(text: str, *, base_style: str = "") -> Text:
    """Render inline bold/italic/code spans so cells and list items don't leak
    raw Markdown punctuation like backticks."""

    result = Text(style=base_style)
    for part in _INLINE_RE.split(text):
        if not part:
            continue
        link_match = _LINK_RE.match(part)
        if link_match:
            label, url = link_match.group(1), link_match.group(2)
            # Render the link text as a terminal hyperlink so the label shows and
            # the URL is preserved (clickable) instead of leaking raw "](url)".
            result.append(label, style=Style(link=url))
        elif part.startswith("**") and part.endswith("**") and len(part) > 4:
            result.append(part[2:-2], style="bold")
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            result.append(part[1:-1], style="cyan")
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            result.append(part[1:-1], style="italic")
        else:
            result.append(part)
    return result


def _print_renderable_compact(console: Console, renderable: RenderableType) -> None:
    with console.capture() as capture:
        console.print(renderable)
    output = _trim_blank_rendered_lines(capture.get())
    if output:
        console.file.write(output)
        if not output.endswith("\n"):
            console.file.write("\n")
        console.file.flush()


def _trim_blank_rendered_lines(output: str) -> str:
    lines = output.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _is_quote_line(line: str) -> bool:
    return line.lstrip().startswith(">")


def _is_table_start(lines: list[str], index: int) -> bool:
    return index + 1 < len(lines) and _is_table_row(lines[index]) and _is_table_separator(lines[index + 1])


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _is_loose_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


def _is_table_continuation(line: str, previous_line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _is_loose_table_row(stripped):
        return True
    if "|" in stripped:
        return True
    previous = previous_line.strip()
    return previous.startswith("|") and not previous.endswith("|") and stripped.startswith(("• ", "- ", "* "))


def _is_table_separator(line: str) -> bool:
    if not _is_table_row(line):
        return False
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(cell and "-" in cell and set(cell) <= {"-", ":", " "} for cell in cells)


def _table_is_malformed(lines: list[str]) -> bool:
    body = lines[2:]
    return any(not _is_table_row(line) or "| |" in line for line in body)


def _is_separator_text(text: str) -> bool:
    compact = text.replace(" ", "")
    return bool(compact) and set(compact) <= {"-", ":", "|"}


def _parse_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in stripped:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append("".join(current).strip())
    return cells


def _fit_row(row: list[str], width: int) -> list[str]:
    if len(row) == width:
        return row
    if len(row) > width:
        return row[:width]
    return row + [""] * (width - len(row))


def _table_is_too_wide(headers: list[str], rows: list[list[str]], console_width: int) -> bool:
    if console_width < 36:
        return True
    columns = list(zip(headers, *rows, strict=False))
    estimated = sum(max(display_width(cell.strip()) for cell in column) for column in columns)
    estimated += max(0, len(headers) - 1) * 2
    return estimated > max(20, console_width - 4)

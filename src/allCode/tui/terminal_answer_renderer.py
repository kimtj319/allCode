"""Final answer rendering for the terminal-native UI."""

from __future__ import annotations

import io
import re

from rich.console import Console

from allCode.tui.markdown_normalizer import normalize_agent_markdown
from allCode.tui.terminal_markdown_blocks import render_compact_markdown

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)

# Codex marks an assistant turn with a dim bullet and indents the whole answer
# body two columns to align under it.
_MARKER_TTY = "\x1b[2m•\x1b[0m "
_MARKER_PLAIN = "• "
_INDENT = "  "


class TerminalAnswerRenderer:
    """Normalize and render assistant answers Codex-style: a leading bullet marker
    with the whole answer body indented two columns."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self._emitted = False
        self._last_offset = False
        self._marker_done = False

    def reset(self) -> None:
        """Reset marker/spacing state at the start of a new assistant answer."""

        self._emitted = False
        self._last_offset = False
        self._marker_done = False

    def render(self, text: str) -> None:
        normalized = normalize_terminal_markdown(text)
        if not normalized.strip():
            return
        width = max(10, self.console.width - len(_INDENT))
        scratch = Console(
            file=io.StringIO(),
            force_terminal=self.console.is_terminal,
            color_system="truecolor" if self.console.is_terminal else None,
            width=width,
            highlight=False,
        )
        self._emitted, self._last_offset = render_compact_markdown(
            scratch,
            normalized,
            emitted=self._emitted,
            last_offset=self._last_offset,
        )
        rendered = scratch.file.getvalue()
        self.console.file.write(self._indent(rendered))
        self.console.file.flush()

    def _indent(self, rendered: str) -> str:
        lines = rendered.split("\n")
        # render_compact_markdown ends each block with a newline, so the split
        # leaves a trailing empty element; drop it and re-add a single newline.
        trailing_newline = lines and lines[-1] == ""
        if trailing_newline:
            lines = lines[:-1]
        out: list[str] = []
        for line in lines:
            if not line:
                out.append("")
                continue
            if not self._marker_done:
                marker = _MARKER_TTY if self.console.is_terminal else _MARKER_PLAIN
                out.append(marker + line)
                self._marker_done = True
            else:
                out.append(_INDENT + line)
        text = "\n".join(out)
        if trailing_newline:
            text += "\n"
        return text


def normalize_terminal_markdown(source: str) -> str:
    text = _BR_RE.sub("\n", source)
    return normalize_agent_markdown(text)

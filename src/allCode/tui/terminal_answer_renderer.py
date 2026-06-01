"""Final answer rendering for the terminal-native UI."""

from __future__ import annotations

import re

from rich.console import Console
from rich.markdown import Markdown

from allCode.tui.markdown_normalizer import normalize_agent_markdown

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


class TerminalAnswerRenderer:
    """Normalize and render assistant answers without leaking raw HTML breaks."""

    def __init__(self, console: Console) -> None:
        self.console = console

    def render(self, text: str) -> None:
        normalized = normalize_terminal_markdown(text)
        if normalized.strip():
            self.console.print(Markdown(normalized))


def normalize_terminal_markdown(source: str) -> str:
    text = _BR_RE.sub("\n", source)
    return normalize_agent_markdown(text)

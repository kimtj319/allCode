"""Cell-to-widget rendering helpers for the Textual transcript."""

from __future__ import annotations

from allCode.tui.markdown import ROLE_TITLES
from allCode.tui.markdown_normalizer import normalize_agent_markdown
from allCode.tui.transcript_cells import TranscriptCell

try:
    from textual.widgets import Markdown

    TEXTUAL_WIDGETS_AVAILABLE = True
except ModuleNotFoundError:
    Markdown = None
    TEXTUAL_WIDGETS_AVAILABLE = False


def cell_to_markdown(cell: TranscriptCell) -> str:
    """Return Markdown suitable for a single transcript cell."""

    content = cell.content.strip()
    if cell.kind == "user":
        return _quote(content)
    if cell.kind in {"assistant", "assistant_stream"}:
        return _assistant(content)
    if cell.kind == "tool":
        return _fenced("Tool", content)
    if cell.kind == "error":
        return f"**Error**\n\n> {content}"
    if cell.kind == "approval":
        return f"**Approval**\n\n{content}"
    if cell.kind in {"validation", "status"}:
        return f"*{content}*"
    if cell.kind == "diff":
        return _fenced("Diff", content, language="diff")
    title = ROLE_TITLES.get(cell.kind.upper(), cell.title or "Status")
    return f"**{title}**\n\n{content}"


def make_cell_widget(cell: TranscriptCell):
    if not TEXTUAL_WIDGETS_AVAILABLE:
        raise RuntimeError("Textual widgets are not available.")
    widget = Markdown(cell_to_markdown(cell), classes=f"transcript-cell {cell.kind}")
    widget.can_focus = False
    return widget


def update_cell_widget(widget, cell: TranscriptCell) -> None:
    widget.update(cell_to_markdown(cell))


def _quote(content: str) -> str:
    if not content:
        return "> "
    return "\n".join(f"> {line}" if line else ">" for line in content.splitlines())


def _assistant(content: str) -> str:
    if not content:
        return ""
    return normalize_agent_markdown(content)


def _fenced(title: str, content: str, *, language: str = "text") -> str:
    return f"**{title}**\n\n```{language}\n{content}\n```"

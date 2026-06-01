"""Owning container for terminal composer frame state."""

from __future__ import annotations

from dataclasses import dataclass, field

from allCode.tui.terminal_footer import FooterProps, TerminalFooterRenderer
from allCode.tui.terminal_frame import StyledLine, TerminalFrame
from allCode.tui.terminal_overlay import OverlayView


@dataclass
class BottomPaneRenderInput:
    input_lines: list[str]
    cursor_row: int
    cursor_col: int
    footer: FooterProps
    overlay: OverlayView | None = None


class TerminalBottomPane:
    """Build bottom-pane frames without knowing about agent execution."""

    def __init__(self, *, footer_renderer: TerminalFooterRenderer | None = None) -> None:
        self.footer_renderer = footer_renderer or TerminalFooterRenderer()

    def frame(self, render_input: BottomPaneRenderInput, *, width: int) -> TerminalFrame:
        overlay_lines = render_input.overlay.render_lines() if render_input.overlay is not None else []
        return TerminalFrame(
            input_lines=[StyledLine(text=line) for line in render_input.input_lines],
            cursor_row=render_input.cursor_row,
            cursor_col=render_input.cursor_col,
            overlay_lines=overlay_lines,
            footer_lines=self.footer_renderer.render(render_input.footer, width=width - 3),
        )

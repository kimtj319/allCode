"""Owning container for terminal composer frame state."""

from __future__ import annotations

from dataclasses import dataclass

from allCode.tui.terminal_activity import ActivityProps, TerminalActivityRenderer
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
    activity: ActivityProps | None = None


class TerminalBottomPane:
    """Build bottom-pane frames without knowing about agent execution."""

    def __init__(
        self,
        *,
        footer_renderer: TerminalFooterRenderer | None = None,
        activity_renderer: TerminalActivityRenderer | None = None,
    ) -> None:
        self.footer_renderer = footer_renderer or TerminalFooterRenderer()
        self.activity_renderer = activity_renderer or TerminalActivityRenderer()

    def frame(self, render_input: BottomPaneRenderInput, *, width: int) -> TerminalFrame:
        overlay_lines = render_input.overlay.render_lines() if render_input.overlay is not None else []
        activity_lines = self.activity_renderer.render(render_input.activity or ActivityProps())
        return TerminalFrame(
            input_lines=[StyledLine(text=line) for line in render_input.input_lines],
            cursor_row=render_input.cursor_row,
            cursor_col=render_input.cursor_col,
            overlay_lines=overlay_lines,
            footer_lines=self.footer_renderer.render(render_input.footer, width=width - 3),
            activity_lines=activity_lines,
            spacer_after_activity=bool(activity_lines),
        )

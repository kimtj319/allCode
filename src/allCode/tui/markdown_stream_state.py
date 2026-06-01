"""Source-backed Markdown streaming state."""

from __future__ import annotations

from allCode.tui.markdown_normalizer import normalize_agent_markdown
from allCode.tui.table_detect import table_holdback_start


class MarkdownStreamState:
    """Track stable Markdown and mutable tail source for streaming answers."""

    def __init__(self) -> None:
        self.raw_source = ""
        self.committed_source_len = 0
        self.stable_source_len = 0
        self.mutable_tail_start = 0
        self.open_fence = False
        self.table_holdback_start: int | None = None

    def reset(self) -> None:
        self.raw_source = ""
        self.committed_source_len = 0
        self.stable_source_len = 0
        self.mutable_tail_start = 0
        self.open_fence = False
        self.table_holdback_start = None

    def append(self, delta: str) -> str:
        self.raw_source += delta
        self._recompute_boundaries()
        return self.visible_source()

    def flush(self) -> str:
        source = self.visible_source(final=True)
        self.reset()
        return source

    def visible_source(self, *, final: bool = False) -> str:
        if final:
            return normalize_agent_markdown(self.raw_source)
        return normalize_agent_markdown(self.raw_source[: self.stable_source_len] + self.raw_source[self.mutable_tail_start :])

    def stable_source(self) -> str:
        return normalize_agent_markdown(self.raw_source[: self.stable_source_len])

    def mutable_tail(self) -> str:
        return normalize_agent_markdown(self.raw_source[self.mutable_tail_start :])

    def _recompute_boundaries(self) -> None:
        self.open_fence = self.raw_source.count("```") % 2 == 1
        last_newline = self.raw_source.rfind("\n")
        stable = len(self.raw_source) if last_newline < 0 else last_newline + 1
        holdback = table_holdback_start(self.raw_source[:stable])
        if holdback is not None:
            self.table_holdback_start = holdback
            stable = min(stable, holdback)
        else:
            self.table_holdback_start = None
        if self.open_fence:
            fence_start = self.raw_source.rfind("```")
            if fence_start >= 0:
                stable = min(stable, fence_start)
        self.stable_source_len = max(0, stable)
        self.mutable_tail_start = self.stable_source_len

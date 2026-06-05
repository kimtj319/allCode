"""Parser protocol for source intelligence backends."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from allCode.workspace.source_intelligence.schema import SourceFileAnalysis


class SourceParser(Protocol):
    @property
    def available(self) -> bool:
        ...

    def supports(self, path: str | Path) -> bool:
        ...

    def analyze_text(self, *, path: str | Path, text: str) -> SourceFileAnalysis:
        ...

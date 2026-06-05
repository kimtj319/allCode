"""Optional read-only LSP enrichment contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from allCode.workspace.source_intelligence.schema import SourceFileAnalysis, SourceReference, SourceSymbol


class SourceLspClient(Protocol):
    @property
    def available(self) -> bool:
        ...

    def enrich(self, analysis: SourceFileAnalysis, *, workspace_root: str | Path) -> SourceFileAnalysis:
        ...


class DisabledLspClient:
    @property
    def available(self) -> bool:
        return False

    def enrich(self, analysis: SourceFileAnalysis, *, workspace_root: str | Path) -> SourceFileAnalysis:
        return analysis.model_copy(
            update={
                "quality": {
                    **analysis.quality,
                    "lsp_available": False,
                    "lsp_unavailable": "disabled",
                }
            }
        )


class StaticLspClient:
    """Deterministic test client for document symbols and references."""

    def __init__(
        self,
        *,
        symbols: list[SourceSymbol] | None = None,
        references: list[SourceReference] | None = None,
        diagnostics: list[dict[str, object]] | None = None,
        fail_reason: str = "",
    ) -> None:
        self._symbols = symbols or []
        self._references = references or []
        self._diagnostics = diagnostics or []
        self._fail_reason = fail_reason

    @property
    def available(self) -> bool:
        return not self._fail_reason

    def enrich(self, analysis: SourceFileAnalysis, *, workspace_root: str | Path) -> SourceFileAnalysis:
        if self._fail_reason:
            return analysis.model_copy(
                update={
                    "quality": {
                        **analysis.quality,
                        "lsp_available": False,
                        "lsp_unavailable": self._fail_reason,
                    }
                }
            )
        symbols = [*analysis.symbols]
        for symbol in self._symbols:
            if symbol.path == analysis.path and not any((item.name, item.line) == (symbol.name, symbol.line) for item in symbols):
                symbols.append(symbol)
        references = [*analysis.references]
        for reference in self._references:
            if reference.path == analysis.path and reference not in references:
                references.append(reference)
        return analysis.model_copy(
            update={
                "symbols": symbols,
                "references": references,
                "diagnostics": [*analysis.diagnostics, *self._diagnostics],
                "quality": {
                    **analysis.quality,
                    "lsp_available": True,
                    "lsp_symbol_count": len(self._symbols),
                    "lsp_reference_count": len(self._references),
                },
            }
        )

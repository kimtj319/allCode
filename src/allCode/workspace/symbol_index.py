"""Source symbol extraction facade."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.workspace.source_intelligence import SourceFileAnalysis, SourceIntelligenceService


class SymbolRecord(CoreModel):
    path: str
    name: str
    kind: str
    signature: str
    line: int = 0
    end_line: int | None = None
    scope: str = ""


class FileSymbols(CoreModel):
    path: str
    imports: list[str] = Field(default_factory=list)
    definitions: list[SymbolRecord] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    analysis: SourceFileAnalysis | None = None


class SymbolIndexer:
    def __init__(self, *, service: SourceIntelligenceService | None = None) -> None:
        self._service = service or SourceIntelligenceService()

    def extract(self, path: str | Path, *, max_bytes: int = 512 * 1024) -> FileSymbols:
        file_path = Path(path)
        service = self._service if self._service.max_bytes == max_bytes else SourceIntelligenceService(max_bytes=max_bytes)
        analysis = service.analyze_file(file_path)
        definitions = [
            SymbolRecord(
                path=symbol.path,
                name=symbol.name,
                kind=symbol.kind,
                signature=symbol.signature,
                line=symbol.line,
                end_line=symbol.end_line,
                scope=symbol.scope,
            )
            for symbol in analysis.symbols
        ]
        return FileSymbols(
            path=str(file_path),
            imports=analysis.compact_imports(),
            definitions=definitions,
            references=analysis.compact_references(),
            analysis=analysis,
        )

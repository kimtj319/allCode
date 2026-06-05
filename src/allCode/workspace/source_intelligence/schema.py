"""JSON-safe source intelligence contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from allCode.core.models import CoreModel

SourceBackend = Literal["python_ast", "tree_sitter", "regex", "generic"]
ReferenceKind = Literal["call", "import", "inheritance", "reference", "definition"]


class SourceSymbol(CoreModel):
    path: str
    name: str
    kind: str
    signature: str
    line: int = 0
    end_line: int | None = None
    scope: str = ""
    parent: str = ""
    visibility: str = "public"
    decorators: list[str] = Field(default_factory=list)
    exported: bool = True


class SourceImport(CoreModel):
    path: str
    module: str
    names: list[str] = Field(default_factory=list)
    alias: str = ""
    line: int = 0
    relative: bool = False


class SourceReference(CoreModel):
    path: str
    symbol: str
    line: int = 0
    kind: ReferenceKind = "reference"
    target_hint: str = ""
    confidence: float = 0.5


class SourceFileAnalysis(CoreModel):
    path: str
    language: str = ""
    backend: SourceBackend = "generic"
    symbols: list[SourceSymbol] = Field(default_factory=list)
    imports: list[SourceImport] = Field(default_factory=list)
    references: list[SourceReference] = Field(default_factory=list)
    diagnostics: list[dict[str, object]] = Field(default_factory=list)
    quality: dict[str, object] = Field(default_factory=dict)

    def compact_definitions(self) -> list[str]:
        return [symbol.signature for symbol in self.symbols if symbol.signature]

    def compact_imports(self) -> list[str]:
        imports: list[str] = []
        for item in self.imports:
            label = item.module
            if item.names:
                label = f"{label}:{','.join(item.names[:4])}" if label else ",".join(item.names[:4])
            if label and label not in imports:
                imports.append(label)
        return imports

    def compact_references(self) -> list[str]:
        refs: list[str] = []
        for item in self.references:
            label = item.symbol if not item.target_hint else f"{item.symbol}->{item.target_hint}"
            if label and label not in refs:
                refs.append(label)
        return refs

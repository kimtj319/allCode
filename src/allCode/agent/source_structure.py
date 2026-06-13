"""Code-structure extraction for read-only inspect summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from allCode.core.models import ToolResult
from allCode.workspace.source_intelligence import SourceFileAnalysis, SourceIntelligenceService


@dataclass(frozen=True)
class CodeStructureSummary:
    path: str
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)

    @property
    def has_evidence(self) -> bool:
        return bool(self.classes or self.functions or self.imports or self.entrypoints)


def read_file_code_summaries(results: list[ToolResult], *, max_files: int = 6) -> list[CodeStructureSummary]:
    summaries: list[CodeStructureSummary] = []
    service = SourceIntelligenceService()
    for result in results:
        if result.name != "read_file" or not result.ok or not result.content:
            continue
        path = _result_path(result)
        if not path:
            continue
        analysis = service.analyze_text(path=path, text=_strip_evidence_bundle(result.content))
        summary = _summary_from_analysis(analysis)
        if summary.has_evidence:
            summaries.append(summary)
        if len(summaries) >= max_files:
            break
    return summaries


def _summary_from_analysis(analysis: SourceFileAnalysis) -> CodeStructureSummary:
    classes: list[str] = []
    functions: list[str] = []
    entrypoints: list[str] = []
    for symbol in analysis.symbols:
        if symbol.kind in {"class", "interface", "enum", "trait"}:
            _append_unique(classes, symbol.scope or symbol.name)
        elif symbol.kind in {"function", "method"}:
            _append_unique(functions, symbol.scope or symbol.name)
            if symbol.name in {"main", "__main__"}:
                _append_unique(entrypoints, symbol.name)
    imports = [item.module for item in analysis.imports if item.module]
    return CodeStructureSummary(
        path=_clean_path(analysis.path),
        classes=classes[:8],
        functions=functions[:12],
        imports=_dedupe(imports)[:8],
        entrypoints=entrypoints[:4],
    )


def _result_path(result: ToolResult) -> str:
    path = str(result.metadata.get("file_path") or "")
    if not path:
        observation = result.metadata.get("observation")
        if isinstance(observation, dict):
            path = str(observation.get("target") or "")
    return _clean_path(path)


def _clean_path(path: str) -> str:
    value = path.strip().strip("`")
    if not value:
        return ""
    parts = Path(value).parts
    for anchor in ("src", "tests", "test"):
        if anchor in parts:
            return "/".join(parts[parts.index(anchor) :])
    if Path(value).is_absolute() and len(parts) > 3:
        return "/".join(parts[-3:])
    return value


def _strip_evidence_bundle(content: str) -> str:
    return content.split("\nEvidence bundle:", 1)[0]


def _dedupe(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        _append_unique(seen, value)
    return seen


def _append_unique(values: list[str], value: str) -> None:
    cleaned = value.strip()
    if cleaned and cleaned not in values:
        values.append(cleaned)

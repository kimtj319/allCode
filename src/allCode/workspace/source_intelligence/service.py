"""Source intelligence orchestration service."""

from __future__ import annotations

from pathlib import Path

from allCode.workspace.source_intelligence.lsp_client import DisabledLspClient, SourceLspClient
from allCode.workspace.source_intelligence.parser_protocol import SourceParser
from allCode.workspace.source_intelligence.python_ast import PythonAstParser
from allCode.workspace.source_intelligence.regex_fallback import RegexFallbackParser
from allCode.workspace.source_intelligence.schema import SourceFileAnalysis
from allCode.workspace.source_intelligence.tree_sitter_parser import TreeSitterParser


class SourceIntelligenceService:
    def __init__(
        self,
        *,
        parsers: list[SourceParser] | None = None,
        fallback: SourceParser | None = None,
        lsp_client: SourceLspClient | None = None,
        max_bytes: int = 512 * 1024,
    ) -> None:
        self.parsers = parsers or [PythonAstParser(), TreeSitterParser()]
        self.fallback = fallback or RegexFallbackParser()
        self.lsp_client = lsp_client or DisabledLspClient()
        self.max_bytes = max_bytes

    def analyze_file(self, path: str | Path, *, workspace_root: str | Path | None = None) -> SourceFileAnalysis:
        file_path = Path(path)
        try:
            if file_path.stat().st_size > self.max_bytes:
                return SourceFileAnalysis(
                    path=str(file_path),
                    language=_language_for_path(file_path),
                    backend="generic",
                    quality={"skipped": True, "reason": "file_too_large"},
                )
            with file_path.open("rb") as handle:
                raw = handle.read(self.max_bytes + 1)
        except OSError as exc:
            return SourceFileAnalysis(
                path=str(file_path),
                language=_language_for_path(file_path),
                backend="generic",
                diagnostics=[{"kind": "read_error", "message": str(exc)}],
                quality={"parsed": False, "read_error": True},
            )
        if b"\0" in raw[:1024] or len(raw) > self.max_bytes:
            return SourceFileAnalysis(
                path=str(file_path),
                language=_language_for_path(file_path),
                backend="generic",
                quality={"skipped": True, "reason": "binary_or_too_large"},
            )
        text = raw.decode("utf-8", errors="replace")
        return self.analyze_text(path=file_path, text=text, workspace_root=workspace_root)

    def analyze_text(
        self,
        *,
        path: str | Path,
        text: str,
        workspace_root: str | Path | None = None,
    ) -> SourceFileAnalysis:
        analysis = self._parse_text(path=path, text=text)
        if analysis.diagnostics and any(item.get("fallback_recommended") for item in analysis.diagnostics):
            fallback = self.fallback.analyze_text(path=path, text=text)
            analysis = fallback.model_copy(
                update={
                    "diagnostics": [*analysis.diagnostics, *fallback.diagnostics],
                    "quality": {
                        **fallback.quality,
                        "fallback_from": analysis.backend,
                    },
                }
            )
        return self.lsp_client.enrich(analysis, workspace_root=workspace_root or Path(path).parent)

    def _parse_text(self, *, path: str | Path, text: str) -> SourceFileAnalysis:
        for parser in self.parsers:
            if parser.available and parser.supports(path):
                return parser.analyze_text(path=path, text=text)
        return self.fallback.analyze_text(path=path, text=text)


def _language_for_path(path: Path) -> str:
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".md": "markdown",
    }.get(path.suffix.lower(), "text")

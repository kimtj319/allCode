"""Regex and generic fallback parsers for source intelligence."""

from __future__ import annotations

from pathlib import Path
import re

from allCode.workspace.source_intelligence.schema import SourceFileAnalysis, SourceImport, SourceReference, SourceSymbol


class RegexFallbackParser:
    @property
    def available(self) -> bool:
        return True

    def supports(self, path: str | Path) -> bool:
        return True

    def analyze_text(self, *, path: str | Path, text: str) -> SourceFileAnalysis:
        path_text = str(path)
        language = _language_for_path(path_text)
        symbols: list[SourceSymbol] = []
        imports: list[SourceImport] = []
        references: list[SourceReference] = []
        lines = text.splitlines()
        for index, line in enumerate(lines[:800], start=1):
            stripped = line.strip()
            _extract_import(path_text, stripped, index, imports, references)
            for pattern, kind, prefix in _definition_patterns(language):
                match = re.search(pattern, stripped)
                if not match:
                    continue
                name = match.group(1)
                signature = match.group(0).strip()
                symbols.append(
                    SourceSymbol(
                        path=path_text,
                        name=name,
                        kind=kind,
                        signature=signature or f"{prefix} {name}",
                        line=index,
                        scope=name,
                        visibility="private" if name.startswith("_") else "public",
                        exported=not name.startswith("_"),
                    )
                )
            for call in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*\(", stripped):
                symbol = call.group(1)
                if symbol in {"if", "for", "while", "switch", "return"}:
                    continue
                references.append(
                    SourceReference(path=path_text, symbol=symbol, line=index, kind="call", target_hint=symbol, confidence=0.35)
                )
        backend = "regex" if symbols or imports or references else "generic"
        return SourceFileAnalysis(
            path=path_text,
            language=language,
            backend=backend,
            symbols=symbols[:120],
            imports=imports[:80],
            references=references[:160],
            quality={
                "parsed": bool(symbols or imports or references),
                "fallback": True,
                "symbol_count": len(symbols),
                "import_count": len(imports),
                "reference_count": len(references),
            },
        )


def _extract_import(
    path: str,
    line: str,
    line_number: int,
    imports: list[SourceImport],
    references: list[SourceReference],
) -> None:
    python_from = re.match(r"from\s+([A-Za-z0-9_\.]+)\s+import\s+(.+)", line)
    python_import = re.match(r"import\s+(.+)", line)
    js_import = re.match(r"import\s+(?:.+?\s+from\s+)?['\"]([^'\"]+)['\"]", line)
    java_import = re.match(r"import\s+([A-Za-z0-9_.*]+);", line)
    if js_import:
        module = js_import.group(1)
        imports.append(SourceImport(path=path, module=module, line=line_number))
        references.append(SourceReference(path=path, symbol=module, line=line_number, kind="import", target_hint=module, confidence=0.75))
        return
    if python_from:
        module = python_from.group(1)
        names = [item.strip().split(" as ", 1)[0] for item in python_from.group(2).split(",")]
        imports.append(SourceImport(path=path, module=module, names=[item for item in names if item], line=line_number))
        references.append(SourceReference(path=path, symbol=module, line=line_number, kind="import", target_hint=module, confidence=0.8))
        return
    if python_import:
        module = python_import.group(1).split(",", 1)[0].strip().split(" as ", 1)[0]
        imports.append(SourceImport(path=path, module=module, line=line_number))
        references.append(SourceReference(path=path, symbol=module, line=line_number, kind="import", target_hint=module, confidence=0.8))
        return
    if java_import:
        module = java_import.group(1)
        imports.append(SourceImport(path=path, module=module, line=line_number))
        references.append(SourceReference(path=path, symbol=module, line=line_number, kind="import", target_hint=module, confidence=0.75))


def _definition_patterns(language: str) -> list[tuple[str, str, str]]:
    common = [
        (r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b", "class", "class"),
        (r"\binterface\s+([A-Za-z_][A-Za-z0-9_]*)\b", "interface", "interface"),
        (r"\benum\s+([A-Za-z_][A-Za-z0-9_]*)\b", "enum", "enum"),
        (r"\b(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)", "function", "def"),
        (r"\b(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)", "function", "function"),
        (r"\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", "constant", "const"),
        (r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\b", "function", "func"),
        (r"\b(?:pub\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\b", "function", "fn"),
        (r"\b(?:pub\s+)?(?:struct|trait)\s+([A-Za-z_][A-Za-z0-9_]*)\b", "class", "struct"),
    ]
    if language == "markdown":
        return [(r"^#{1,6}\s+(.+)$", "heading", "heading")]
    return common


def _language_for_path(path: str) -> str:
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
    }.get(Path(path).suffix.lower(), "text")

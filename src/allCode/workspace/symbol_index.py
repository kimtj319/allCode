"""Lightweight symbol extraction without external parsers."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from pydantic import Field

from allCode.core.models import CoreModel


class SymbolRecord(CoreModel):
    path: str
    name: str
    kind: str
    signature: str
    line: int = 0


class FileSymbols(CoreModel):
    path: str
    imports: list[str] = Field(default_factory=list)
    definitions: list[SymbolRecord] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class SymbolIndexer:
    def extract(self, path: str | Path, *, max_bytes: int = 512 * 1024) -> FileSymbols:
        file_path = Path(path)
        try:
            if file_path.stat().st_size > max_bytes:
                return FileSymbols(path=str(file_path))
            with file_path.open("rb") as handle:
                raw = handle.read(max_bytes + 1)
        except OSError:
            return FileSymbols(path=str(file_path))
        if b"\0" in raw[:1024] or len(raw) > max_bytes:
            return FileSymbols(path=str(file_path))
        text = raw.decode("utf-8", errors="replace")
        suffix = file_path.suffix.lower()
        if suffix == ".py":
            return self._python(file_path, text)
        if suffix == ".java":
            return self._regex(file_path, text, language="java")
        if suffix in {".js", ".ts", ".tsx"}:
            return self._regex(file_path, text, language="typescript")
        return self._generic(file_path, text)

    def _python(self, path: Path, text: str) -> FileSymbols:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return self._regex(path, text, language="python")
        imports: list[str] = []
        definitions: list[SymbolRecord] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
            elif isinstance(node, ast.ClassDef):
                definitions.append(SymbolRecord(path=str(path), name=node.name, kind="class", signature=f"class {node.name}", line=node.lineno))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [arg.arg for arg in node.args.args]
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                definitions.append(SymbolRecord(path=str(path), name=node.name, kind="function", signature=f"{prefix} {node.name}({', '.join(args)})", line=node.lineno))
        return FileSymbols(path=str(path), imports=[item for item in imports if item], definitions=definitions)

    def _regex(self, path: Path, text: str, *, language: str) -> FileSymbols:
        imports = [line.strip() for line in text.splitlines() if line.strip().startswith(("import ", "from ", "package "))]
        definitions: list[SymbolRecord] = []
        patterns = [
            (r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)", "class"),
            (r"\binterface\s+([A-Za-z_][A-Za-z0-9_]*)", "interface"),
            (r"\benum\s+([A-Za-z_][A-Za-z0-9_]*)", "enum"),
            (r"\b(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)", "function"),
            (r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)", "function"),
        ]
        for pattern, kind in patterns:
            for match in re.finditer(pattern, text):
                name = match.group(1)
                line = text.count("\n", 0, match.start()) + 1
                signature = match.group(0).strip()
                definitions.append(SymbolRecord(path=str(path), name=name, kind=kind, signature=signature, line=line))
        return FileSymbols(path=str(path), imports=imports, definitions=definitions, references=[])

    def _generic(self, path: Path, text: str) -> FileSymbols:
        headings = [line.strip("# ").strip() for line in text.splitlines() if line.startswith("#")]
        imports = [line.strip() for line in text.splitlines() if line.strip().startswith(("import ", "from "))]
        definitions = [SymbolRecord(path=str(path), name=heading, kind="heading", signature=heading) for heading in headings[:20]]
        return FileSymbols(path=str(path), imports=imports, definitions=definitions)

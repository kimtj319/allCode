"""Optional Tree-sitter parser adapter."""

from __future__ import annotations

from pathlib import Path

from allCode.workspace.source_intelligence.regex_fallback import RegexFallbackParser
from allCode.workspace.source_intelligence.schema import SourceFileAnalysis, SourceImport, SourceReference, SourceSymbol

LANGUAGE_BY_SUFFIX = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
}
CLASS_NODE_TYPES = {"class_declaration", "class_definition", "interface_declaration", "enum_declaration", "struct_item", "trait_item", "type_declaration"}
FUNCTION_NODE_TYPES = {"function_declaration", "method_declaration", "function_item", "method_definition", "function_definition"}
IMPORT_NODE_TYPES = {"import_statement", "import_declaration", "use_declaration", "package_clause"}
CALL_NODE_TYPES = {"call_expression"}


class TreeSitterParser:
    def __init__(self) -> None:
        self._fallback = RegexFallbackParser()
        self._get_parser = self._load_get_parser()

    @property
    def available(self) -> bool:
        return self._get_parser is not None

    def supports(self, path: str | Path) -> bool:
        return self.available and Path(path).suffix.lower() in LANGUAGE_BY_SUFFIX

    def analyze_text(self, *, path: str | Path, text: str) -> SourceFileAnalysis:
        if not self.supports(path):
            return self._fallback.analyze_text(path=path, text=text)
        language = LANGUAGE_BY_SUFFIX[Path(path).suffix.lower()]
        try:
            parser = self._get_parser(language)  # type: ignore[misc]
            source = text.encode("utf-8")
            tree = parser.parse(source)
            symbols: list[SourceSymbol] = []
            imports: list[SourceImport] = []
            references: list[SourceReference] = []
            self._walk(tree.root_node, path=str(path), source=source, symbols=symbols, imports=imports, references=references)
            if not symbols and not imports and not references:
                return self._fallback.analyze_text(path=path, text=text)
            return SourceFileAnalysis(
                path=str(path),
                language=language,
                backend="tree_sitter",
                symbols=symbols[:160],
                imports=imports[:120],
                references=references[:200],
                quality={
                    "parsed": True,
                    "tree_sitter_available": True,
                    "symbol_count": len(symbols),
                    "import_count": len(imports),
                    "reference_count": len(references),
                },
            )
        except Exception as exc:
            fallback = self._fallback.analyze_text(path=path, text=text)
            return fallback.model_copy(
                update={
                    "quality": {
                        **fallback.quality,
                        "tree_sitter_available": True,
                        "tree_sitter_error": exc.__class__.__name__,
                    }
                }
            )

    def _walk(self, node, *, path: str, source: bytes, symbols: list[SourceSymbol], imports: list[SourceImport], references: list[SourceReference]) -> None:
        if node.type in CLASS_NODE_TYPES:
            self._record_symbol(node, path=path, source=source, kind="class", symbols=symbols)
        elif node.type in FUNCTION_NODE_TYPES:
            self._record_symbol(node, path=path, source=source, kind="function", symbols=symbols)
        elif node.type in IMPORT_NODE_TYPES:
            text = _node_text(node, source)
            imports.append(SourceImport(path=path, module=_import_module(text), line=node.start_point[0] + 1))
            references.append(SourceReference(path=path, symbol=_import_module(text), line=node.start_point[0] + 1, kind="import", target_hint=text[:120], confidence=0.75))
        elif node.type in CALL_NODE_TYPES:
            text = _node_text(node, source)
            name = text.split("(", 1)[0].strip()
            if name:
                references.append(SourceReference(path=path, symbol=name, line=node.start_point[0] + 1, kind="call", target_hint=name, confidence=0.55))
        for child in node.children:
            self._walk(child, path=path, source=source, symbols=symbols, imports=imports, references=references)

    def _record_symbol(self, node, *, path: str, source: bytes, kind: str, symbols: list[SourceSymbol]) -> None:
        name_node = node.child_by_field_name("name")
        name = _node_text(name_node, source) if name_node is not None else _first_identifier(node, source)
        if not name:
            return
        prefix = "class" if kind == "class" else "function"
        symbols.append(
            SourceSymbol(
                path=path,
                name=name,
                kind=kind,
                signature=f"{prefix} {name}",
                line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                scope=name,
                visibility="private" if name.startswith("_") else "public",
                exported=not name.startswith("_"),
            )
        )

    @staticmethod
    def _load_get_parser():
        try:
            from tree_sitter_language_pack import get_parser
        except Exception:
            return None
        return get_parser


def _node_text(node, source: bytes) -> str:
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace").strip()


def _first_identifier(node, source: bytes) -> str:
    for child in node.children:
        if child.type in {"identifier", "type_identifier", "property_identifier"}:
            return _node_text(child, source)
    return ""


def _import_module(text: str) -> str:
    if " from " in text:
        return text.rsplit(" from ", 1)[-1].strip().strip(";\"'")
    if text.startswith("import "):
        return text.removeprefix("import ").strip().strip(";\"'")
    if text.startswith("use "):
        return text.removeprefix("use ").strip().strip(";")
    if text.startswith("package "):
        return text.removeprefix("package ").strip()
    return text.strip().strip(";\"'")

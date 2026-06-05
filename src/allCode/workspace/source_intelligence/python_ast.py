"""Python stdlib AST parser for source intelligence."""

from __future__ import annotations

import ast
from pathlib import Path

from allCode.workspace.source_intelligence.schema import (
    SourceFileAnalysis,
    SourceImport,
    SourceReference,
    SourceSymbol,
)


class PythonAstParser:
    @property
    def available(self) -> bool:
        return True

    def supports(self, path: str | Path) -> bool:
        return Path(path).suffix.lower() == ".py"

    def analyze_text(self, *, path: str | Path, text: str) -> SourceFileAnalysis:
        path_text = str(path)
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            return SourceFileAnalysis(
                path=path_text,
                language="python",
                backend="python_ast",
                diagnostics=[
                    {
                        "kind": "syntax_error",
                        "message": exc.msg,
                        "line": exc.lineno or 0,
                        "fallback_recommended": True,
                    }
                ],
                quality={"parsed": False, "fallback_recommended": True},
            )
        visitor = _PythonVisitor(path_text)
        visitor.visit(tree)
        return SourceFileAnalysis(
            path=path_text,
            language="python",
            backend="python_ast",
            symbols=visitor.symbols,
            imports=visitor.imports,
            references=visitor.references,
            quality={
                "parsed": True,
                "symbol_count": len(visitor.symbols),
                "import_count": len(visitor.imports),
                "reference_count": len(visitor.references),
            },
        )


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.symbols: list[SourceSymbol] = []
        self.imports: list[SourceImport] = []
        self.references: list[SourceReference] = []
        self._scope: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                SourceImport(
                    path=self.path,
                    module=alias.name,
                    alias=alias.asname or "",
                    line=node.lineno,
                    relative=False,
                )
            )
            self._reference(alias.asname or alias.name.split(".", 1)[0], node.lineno, kind="import", target=alias.name, confidence=0.9)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        names = [alias.name for alias in node.names]
        module = "." * int(node.level or 0) + (node.module or "")
        alias = ",".join(alias.asname for alias in node.names if alias.asname)
        self.imports.append(
            SourceImport(
                path=self.path,
                module=module,
                names=names,
                alias=alias,
                line=node.lineno,
                relative=bool(node.level),
            )
        )
        for name in names:
            self._reference(name, node.lineno, kind="import", target=module, confidence=0.9)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        parent = self._parent
        scope = self._qualified(node.name)
        bases = [_name_for_expr(base) for base in node.bases]
        decorators = [_name_for_expr(item) for item in node.decorator_list]
        self.symbols.append(
            SourceSymbol(
                path=self.path,
                name=node.name,
                kind="class",
                signature=f"class {scope}",
                line=node.lineno,
                end_line=getattr(node, "end_lineno", None),
                scope=scope,
                parent=parent,
                decorators=[item for item in decorators if item],
                exported=not node.name.startswith("_"),
                visibility=_visibility(node.name),
            )
        )
        for base in bases:
            if base:
                self._reference(base, node.lineno, kind="inheritance", target=base, confidence=0.85)
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node, async_def=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node, async_def=True)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._scope:
            self.generic_visit(node)
            return
        for target in node.targets:
            name = _name_for_expr(target)
            if name and name.isupper() and not name.startswith("_"):
                self.symbols.append(
                    SourceSymbol(
                        path=self.path,
                        name=name,
                        kind="constant",
                        signature=f"{name} = ...",
                        line=node.lineno,
                        end_line=getattr(node, "end_lineno", None),
                        scope=name,
                        exported=True,
                    )
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _name_for_expr(node.func)
        if name:
            self._reference(name, node.lineno, kind="call", target=name, confidence=0.7)
        self.generic_visit(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, async_def: bool) -> None:
        parent = self._parent
        scope = self._qualified(node.name)
        prefix = "async def" if async_def else "def"
        args = [arg.arg for arg in node.args.args]
        decorators = [_name_for_expr(item) for item in node.decorator_list]
        self.symbols.append(
            SourceSymbol(
                path=self.path,
                name=node.name,
                kind="function",
                signature=f"{prefix} {scope}({', '.join(args)})",
                line=node.lineno,
                end_line=getattr(node, "end_lineno", None),
                scope=scope,
                parent=parent,
                decorators=[item for item in decorators if item],
                exported=not node.name.startswith("_"),
                visibility=_visibility(node.name),
            )
        )
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    @property
    def _parent(self) -> str:
        return ".".join(self._scope)

    def _qualified(self, name: str) -> str:
        if not self._scope:
            return name
        return ".".join([*self._scope, name])

    def _reference(self, symbol: str, line: int, *, kind, target: str = "", confidence: float = 0.5) -> None:
        cleaned = symbol.strip()
        if not cleaned:
            return
        self.references.append(
            SourceReference(
                path=self.path,
                symbol=cleaned,
                line=line,
                kind=kind,
                target_hint=target,
                confidence=confidence,
            )
        )


def _name_for_expr(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name_for_expr(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _name_for_expr(node.func)
    if isinstance(node, ast.Subscript):
        return _name_for_expr(node.value)
    if isinstance(node, ast.Constant):
        return str(node.value)
    return ""


def _visibility(name: str) -> str:
    return "private" if name.startswith("_") else "public"

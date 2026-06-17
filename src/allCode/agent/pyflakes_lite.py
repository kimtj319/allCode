"""Dependency-free, conservative static checks for Python edits.

``compileall`` only catches *syntax* errors. Editor/LSP diagnostics (and tools
like pyflakes) also catch a class of bugs that import cleanly but are obviously
wrong: a name that is used but bound nowhere (a typo), and an import that is
never used. This module reimplements just those two checks with the standard
library so the edit→validate loop can surface them without requiring pyflakes,
ruff, or any package to be installed in the target environment.

It is deliberately *conservative* — it errs toward silence to avoid
manufacturing a spurious validation failure on otherwise-fine code:

* Undefined names are reported only when the name is bound nowhere in the whole
  module (any function/class scope counts as a binding). This misses some real
  cases a full scope analysis would catch, but it never flags a name that is
  legitimately defined in an enclosing or sibling scope.
* Files that use ``from x import *`` are skipped entirely (a star import can
  supply any name, so neither check can be trusted).
* Unused-import reporting skips ``__init__.py`` (re-exports), ``__future__``
  imports, names listed in ``__all__``, and lines carrying ``# noqa``.

Run as ``python pyflakes_lite.py <root>``: prints one ``path:line: message`` per
finding and exits non-zero when any are found (so it slots into validation).
"""

from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

_SKIP_DIRS = {".venv", "venv", "__pycache__", "node_modules", ".git", ".mypy_cache", ".ruff_cache", "build", "dist"}
_BUILTINS = set(dir(builtins)) | {
    "__name__",
    "__file__",
    "__doc__",
    "__all__",
    "__spec__",
    "__loader__",
    "__package__",
    "__builtins__",
    "__class__",
    "__dict__",
    "__module__",
    "__qualname__",
    "__annotations__",
    "__path__",
}


class _BindingCollector(ast.NodeVisitor):
    """Collect every name bound anywhere in the module, plus import bindings."""

    def __init__(self) -> None:
        self.bound: set[str] = set()
        self.has_star_import = False
        # name -> (lineno, source-ish) for imports, to report unused ones
        self.imports: dict[str, int] = {}
        self.import_from_future: set[str] = set()

    def _bind(self, name: str | None) -> None:
        if name:
            self.bound.add(name)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            bound = alias.asname or alias.name.split(".")[0]
            self._bind(bound)
            self.imports[bound] = node.lineno
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if any(alias.name == "*" for alias in node.names):
            self.has_star_import = True
        for alias in node.names:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name
            self._bind(bound)
            if node.module == "__future__":
                self.import_from_future.add(bound)
            else:
                self.imports[bound] = node.lineno
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._bind(node.name)
        self._bind_args(node.args)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._bind(node.name)
        self._bind_args(node.args)
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._bind_args(node.args)
        self.generic_visit(node)

    def _bind_args(self, args: ast.arguments) -> None:
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            self._bind(arg.arg)
        if args.vararg:
            self._bind(args.vararg.arg)
        if args.kwarg:
            self._bind(args.kwarg.arg)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._bind(node.name)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self._bind(node.id)
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:  # comprehension/except-handler safety
        self._bind(node.arg)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        for name in node.names:
            self._bind(name)
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        for name in node.names:
            self._bind(name)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._bind(node.name)
        self.generic_visit(node)


def _names_in_annotation(node: ast.AST | None, used: set[str]) -> None:
    """Collect names referenced by a type annotation, including string/forward
    refs like ``"HooksConfig | None"`` (common for TYPE_CHECKING imports)."""
    if node is None:
        return
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            parsed = ast.parse(node.value, mode="eval")
        except SyntaxError:
            return
        for inner in ast.walk(parsed):
            if isinstance(inner, ast.Name):
                used.add(inner.id)
        return
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name):
            used.add(inner.id)
        elif isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            _names_in_annotation(inner, used)


def _used_names(tree: ast.AST) -> set[str]:
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            # `a.b` — the root Name is captured by the Name branch; attribute
            # access also "uses" the module bound by `import a`.
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                used.add(base.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _names_in_annotation(node.returns, used)
        elif isinstance(node, ast.AnnAssign):
            _names_in_annotation(node.annotation, used)
        elif isinstance(node, ast.arg):
            _names_in_annotation(node.annotation, used)
    return used


def _noqa_lines(source: str) -> set[int]:
    return {i for i, line in enumerate(source.splitlines(), start=1) if "# noqa" in line or "#noqa" in line}


def check_source(source: str, *, path: str, undefined_only: bool = False) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []  # compileall already reports syntax errors
    collector = _BindingCollector()
    collector.visit(tree)
    if collector.has_star_import:
        return []
    used = _used_names(tree)
    noqa = _noqa_lines(source)
    findings: list[tuple[int, str]] = []

    # __all__ string entries count as "used" re-exports.
    exported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                exported.update(
                    elt.value for elt in node.value.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                )

    # Unused-import findings can fire on re-export hubs (a module that imports
    # names only so other modules can import them from it), which are legitimate.
    # So they are excluded from the always-on validation run (undefined_only) and
    # surfaced only when explicitly requested.
    is_init = Path(path).name == "__init__.py"
    if not undefined_only and not is_init:
        for name, lineno in sorted(collector.imports.items(), key=lambda kv: kv[1]):
            if name in collector.import_from_future or name in used or name in exported:
                continue
            if lineno in noqa:
                continue
            findings.append((lineno, f"'{name}' imported but unused"))

    # Undefined: a Load name bound nowhere in the module and not a builtin.
    bound = collector.bound | collector.import_from_future
    seen_undefined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            name = node.id
            if name in bound or name in _BUILTINS or name in seen_undefined:
                continue
            if node.lineno in noqa:
                continue
            seen_undefined.add(name)
            findings.append((node.lineno, f"undefined name '{name}'"))

    findings.sort()
    return [f"{path}:{lineno}: {message}" for lineno, message in findings]


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def check_path(root: str, *, undefined_only: bool = False) -> list[str]:
    base = Path(root).expanduser()
    findings: list[str] = []
    targets = [base] if base.is_file() else _iter_python_files(base)
    for path in targets:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(path.relative_to(base)) if base.is_dir() else str(path)
        findings.extend(check_source(source, path=rel, undefined_only=undefined_only))
    return findings


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    undefined_only = "--undefined-only" in argv[1:]
    root = args[0] if args else "."
    findings = check_path(root, undefined_only=undefined_only)
    for line in findings:
        print(line)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

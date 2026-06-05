"""AST-level public API obligation checks for generated project files."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from allCode.agent.task_plan import PlannedFile, ProjectPlan
from allCode.core.result import CompletionEvidence
from allCode.workspace.path_resolver import safe_resolve_under_root

SUPPORTED_SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs"}
CONTROL_WORDS = {"catch", "class", "constructor", "for", "function", "get", "if", "set", "switch", "while"}


def api_obligation_errors(
    *,
    workspace_root: str | Path,
    plan: ProjectPlan,
    completion_evidence: CompletionEvidence,
) -> list[str]:
    errors: list[str] = []
    planned_symbols = _planned_public_symbols(plan)
    if not planned_symbols and not completion_evidence.public_api_expectations:
        return errors
    target_root = safe_resolve_under_root(workspace_root, plan.target_root)
    actual_symbols_by_path = _actual_symbols(target_root, planned_symbols)
    for relative_path, expected_symbols in planned_symbols.items():
        actual = actual_symbols_by_path.get(relative_path, set())
        missing = sorted(
            symbol
            for symbol in expected_symbols
            if not _expected_symbol_satisfied(actual, symbol)
        )
        if missing:
            errors.append(f"public API obligation missing in {relative_path}: {', '.join(missing[:6])}")
    expectation_names = _expectation_symbol_names(completion_evidence.public_api_expectations)
    if expectation_names:
        all_actual = set().union(*actual_symbols_by_path.values()) if actual_symbols_by_path else set()
        missing = sorted(
            name
            for name in expectation_names
            if not any(_symbol_satisfies_expectation(symbol, name) for symbol in all_actual)
        )
        if missing:
            errors.append("public API expectations not satisfied: " + ", ".join(missing[:6]))
    return errors


def _planned_public_symbols(plan: ProjectPlan) -> dict[str, set[str]]:
    latest: dict[str, PlannedFile] = {}
    symbols: dict[str, set[str]] = {}
    for obligation in plan.api_obligations:
        symbols.setdefault(obligation.path, set()).add(obligation.symbol)
    for planned_file in plan.files:
        if planned_file.stage == "tests" or _looks_test_path(planned_file.path):
            continue
        if Path(planned_file.path).suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            continue
        latest[planned_file.path] = planned_file
    for path, planned_file in latest.items():
        suffix = Path(planned_file.path).suffix.lower()
        parsed = _extract_file_symbols(planned_file.content, suffix)
        if parsed:
            symbols.setdefault(path, set()).update(parsed)
    return symbols


def _actual_symbols(target_root: Path, planned_symbols: dict[str, set[str]]) -> dict[str, set[str]]:
    actual: dict[str, set[str]] = {}
    for relative_path in planned_symbols:
        path = target_root / relative_path
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            actual[relative_path] = set()
            continue
        suffix = Path(relative_path).suffix.lower()
        actual[relative_path] = _extract_file_symbols(content, suffix)
    return actual


def _python_public_symbols(content: str) -> set[str]:
    try:
        module = ast.parse(content)
    except SyntaxError:
        return set()
    symbols: set[str] = set()
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            symbols.add(node.name)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            symbols.add(node.name)
            symbols.update(_public_class_methods(node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    symbols.update(_static_all_exports(node.value))
                elif isinstance(target, ast.Name) and not target.id.startswith("_"):
                    symbols.add(target.id)
    return symbols


def _public_class_methods(node: ast.ClassDef) -> set[str]:
    methods: set[str] = set()
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
            methods.add(f"{node.name}.{child.name}")
    return methods


def _static_all_exports(value: ast.AST) -> set[str]:
    if not isinstance(value, (ast.List, ast.Tuple)):
        return set()
    exports: set[str] = set()
    for element in value.elts:
        if isinstance(element, ast.Constant) and isinstance(element.value, str) and element.value.strip():
            exports.add(f"__all__:{element.value.strip()}")
    return exports


def _expectation_symbol_names(expectations: list[str]) -> set[str]:
    names: set[str] = set()
    for expectation in expectations:
        text = str(expectation)
        for pattern in (
            r"\bexport\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b",
            r"\bprovide attribute or method\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b",
            r"\bin\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b",
        ):
            match = re.search(pattern, text)
            if match:
                names.add(match.group("name"))
                break
    return names


def _symbol_satisfies_expectation(actual_symbol: str, expected_name: str) -> bool:
    return actual_symbol == expected_name or actual_symbol.endswith(f".{expected_name}")


def _expected_symbol_satisfied(actual_symbols: set[str], expected_symbol: str) -> bool:
    if expected_symbol.startswith("__all__:"):
        return expected_symbol in actual_symbols
    if expected_symbol in actual_symbols:
        return True
    if "." not in expected_symbol:
        return any(symbol.endswith(f".{expected_symbol}") for symbol in actual_symbols)
    return False


def _looks_test_path(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    name = Path(lowered).name
    return lowered.startswith("tests/") or "/tests/" in lowered or name.startswith("test_")


def _extract_file_symbols(content: str, suffix: str) -> set[str]:
    if suffix == ".py":
        return _python_public_symbols(content)
    return _non_python_public_symbols(content, suffix)


def _non_python_public_symbols(content: str, suffix: str) -> set[str]:
    content = _strip_c_like_comments(content)
    symbols: set[str] = set()

    if suffix in {".js", ".ts", ".jsx", ".tsx"}:
        for m in re.finditer(r"\bexport\s+(?:async\s+)?function\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)", content):
            symbols.add(m.group("name"))
        for m in re.finditer(r"\bexport\s+class\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)", content):
            symbols.add(m.group("name"))
        for m in re.finditer(r"\bexport\s+const\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(", content):
            symbols.add(m.group("name"))
        for class_name, body in _iter_braced_blocks(content, r"\bclass\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)"):
            if class_name.startswith("_"):
                continue
            symbols.add(class_name)
            for method_name in _js_class_methods(body):
                symbols.add(f"{class_name}.{method_name}")

    elif suffix == ".go":
        for m in re.finditer(r"\bfunc\s+(?P<name>[A-Z][A-Za-z0-9_]*)\s*\(", content):
            symbols.add(m.group("name"))
        for m in re.finditer(r"\bfunc\s*\(\s*(?:\w+\s+)?\*?(?P<receiver>[A-Za-z0-9_]+)\s*\)\s*(?P<name>[A-Z][A-Za-z0-9_]*)\s*\(", content):
            receiver = m.group("receiver")
            name = m.group("name")
            symbols.add(f"{receiver}.{name}")
            symbols.add(name)

    elif suffix == ".rs":
        for m in re.finditer(r"\bpub\s+fn\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)", content):
            symbols.add(m.group("name"))
        for m in re.finditer(r"\bpub\s+(?:struct|enum)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)", content):
            symbols.add(m.group("name"))
        for type_name, body in _iter_braced_blocks(
            content,
            r"\bimpl(?:\s*<[^>]+>)?\s+(?:(?:[A-Za-z_][A-Za-z0-9_:]*)\s+for\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
        ):
            for method in re.finditer(r"\bpub\s+fn\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)", body):
                symbols.add(f"{type_name}.{method.group('name')}")

    elif suffix == ".java":
        for m in re.finditer(r"\bpublic\s+class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)", content):
            symbols.add(m.group("name"))
        for class_name, body in _iter_braced_blocks(content, r"\bclass\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"):
            if class_name.startswith("_"):
                continue
            symbols.add(class_name)
            for method in re.finditer(r"\bpublic\s+(?:static\s+)?(?:final\s+)?(?:[\w<>\[\], ?]+\s+)+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(", body):
                method_name = method.group("name")
                if method_name not in CONTROL_WORDS and not method_name.startswith("_"):
                    symbols.add(f"{class_name}.{method_name}")

    return symbols


def _strip_c_like_comments(content: str) -> str:
    without_blocks = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    return re.sub(r"//.*", "", without_blocks)


def _iter_braced_blocks(content: str, pattern: str):
    for match in re.finditer(pattern, content):
        name = match.group("name")
        brace_index = content.find("{", match.end())
        if brace_index < 0:
            continue
        end_index = _matching_brace_index(content, brace_index)
        if end_index is None:
            continue
        yield name, content[brace_index + 1 : end_index]


def _matching_brace_index(content: str, open_index: int) -> int | None:
    depth = 0
    for index in range(open_index, len(content)):
        char = content[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _js_class_methods(body: str) -> set[str]:
    methods: set[str] = set()
    for match in re.finditer(r"\b(?:async\s+)?(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*\([^)]*\)\s*\{", body):
        name = match.group("name")
        if name not in CONTROL_WORDS and not name.startswith("_"):
            methods.add(name)
    return methods

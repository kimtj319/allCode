"""Completion checks for generation workflows."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from pydantic import Field

from allCode.agent.api_obligation_checker import api_obligation_errors, planned_public_api_symbols
from allCode.agent.documentation_cli_consistency import cli_documentation_reference_errors
from allCode.agent.obligation_matrix import build_obligation_matrix
from allCode.agent.task_plan import ProjectPlan
from allCode.agent.validation_runner import ValidationResult
from allCode.core.models import CoreModel
from allCode.core.result import CompletionEvidence
from allCode.workspace.path_resolver import safe_resolve_under_root


class CompletionCheck(CoreModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    missing_files: list[str] = Field(default_factory=list)
    empty_files: list[str] = Field(default_factory=list)
    forbidden_files: list[str] = Field(default_factory=list)


class CompletionChecker:
    def check(
        self,
        *,
        workspace_root: str | Path,
        plan: ProjectPlan,
        completion_evidence: CompletionEvidence,
        validation_results: list[ValidationResult],
        final_report: str | None = None,
        validation_required: bool = True,
    ) -> CompletionCheck:
        errors: list[str] = []
        target_root = safe_resolve_under_root(workspace_root, plan.target_root)
        if not target_root.exists() or not target_root.is_dir():
            errors.append(f"target root does not exist: {plan.target_root}")

        missing_files: list[str] = []
        empty_files: list[str] = []
        for relative_path in plan.required_paths():
            path = target_root / relative_path
            if not path.exists():
                missing_files.append(relative_path)
                continue
            if not path.is_file() or path.stat().st_size == 0:
                empty_files.append(relative_path)

        forbidden_files = [path for path in plan.forbidden_files if (target_root / path).exists()]
        if missing_files:
            errors.append("required files are missing")
        if empty_files:
            errors.append("required files are empty")
        errors.extend(_python_syntax_errors(target_root, plan.required_paths()))
        if forbidden_files:
            errors.append("forbidden files were created")
        if not completion_evidence.has_file_change():
            errors.append("no file-change evidence was produced")
        if validation_required:
            if not completion_evidence.validation_commands:
                errors.append("validation was not executed")
            elif completion_evidence.validation_passed is not True:
                errors.append("validation evidence did not succeed")
        if completion_evidence.validation_commands and not validation_results:
            errors.append("validation result details are missing")
        errors.extend(
            api_obligation_errors(
                workspace_root=workspace_root,
                plan=plan,
                completion_evidence=completion_evidence,
            )
        )
        errors.extend(_test_function_errors(target_root, plan))
        errors.extend(_test_coverage_errors(target_root, plan, validation_passed=completion_evidence.validation_passed is True))
        errors.extend(_documentation_reference_errors(target_root, plan))
        errors.extend(cli_documentation_reference_errors(target_root, plan))
        if final_report is not None:
            report_errors = self._check_final_report(final_report, plan, completion_evidence, validation_results)
            errors.extend(report_errors)

        return CompletionCheck(
            ok=not errors,
            errors=errors,
            missing_files=missing_files,
            empty_files=empty_files,
            forbidden_files=forbidden_files,
        )

    def _check_final_report(
        self,
        final_report: str,
        plan: ProjectPlan,
        completion_evidence: CompletionEvidence,
        validation_results: list[ValidationResult],
    ) -> list[str]:
        errors: list[str] = []
        lowered = final_report.lower()
        if plan.target_root.lower() not in lowered:
            errors.append("final report does not mention the target root")
        evidence_files = completion_evidence.created_files + completion_evidence.changed_files
        for changed_file in evidence_files:
            normalized = changed_file.replace("\\", "/")
            relative = normalized.split(plan.target_root.rstrip("/") + "/", 1)[-1]
            if relative not in final_report and normalized not in final_report:
                errors.append(f"final report omits changed file from evidence: {relative}")
                break
        for command in completion_evidence.validation_commands:
            if command not in final_report:
                errors.append("final report omits validation command from evidence")
                break
        expected_results = {"succeeded", "success", "passed", "성공", "통과"} if completion_evidence.validation_passed is True else {"failed", "failure", "실패"}
        if completion_evidence.validation_passed is not None and not any(result in lowered for result in expected_results):
            errors.append("final report omits validation result from evidence")
        if not _mentions_core_functionality(lowered):
            errors.append("final report omits core functionality")
        matrix = build_obligation_matrix(plan=plan, completion_evidence=completion_evidence, validation_results=validation_results)
        if matrix.coverage_status and not _mentions_obligation_coverage(lowered):
            errors.append("final report omits obligation coverage matrix")
        if "remaining risks" not in lowered and "남은 리스크" not in lowered:
            errors.append("final report omits remaining risks")
        if validation_results and validation_results[-1].command not in final_report:
            errors.append("final report omits validation result detail")
        return errors


def _python_syntax_errors(target_root: Path, relative_paths: list[str]) -> list[str]:
    errors: list[str] = []
    for relative_path in relative_paths:
        if not relative_path.endswith(".py"):
            continue
        path = target_root / relative_path
        if not path.exists() or not path.is_file():
            continue
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            location = f"{relative_path}:{exc.lineno or 0}"
            errors.append(f"python syntax error in {location}: {exc.msg}")
        except UnicodeDecodeError as exc:
            errors.append(f"python syntax error in {relative_path}: unable to decode utf-8 source ({exc.reason})")
        except OSError as exc:
            errors.append(f"python syntax error in {relative_path}: unable to read source ({exc.strerror or exc})")
    return errors


def _test_function_errors(target_root: Path, plan: ProjectPlan) -> list[str]:
    """Fail when a required Python test file authors no actual test functions.

    A "no tests ran" pytest result (exit 5) is treated leniently elsewhere so an
    edit to a project without a suite is not blocked forever. But when the plan
    obligates a test file and that file defines zero ``test*`` functions — e.g.
    the model copied the implementation into the test file — the validation pass
    is hollow. Catch it here so a generation turn cannot report success without
    the tests it was required to author.
    """
    errors: list[str] = []
    for relative_path, content in _actual_test_files(target_root, plan):
        if Path(relative_path).suffix.lower() != ".py":
            continue
        if not _has_python_test_functions(content):
            errors.append(
                f"required test file defines no test functions: {relative_path} "
                "(author at least one test_* function so validation exercises real tests)"
            )
    return errors


def _has_python_test_functions(content: str) -> bool:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        # Syntax errors are reported separately; do not double-flag here.
        return True
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            return True
    return False


def _test_coverage_errors(target_root: Path, plan: ProjectPlan, *, validation_passed: bool = False) -> list[str]:
    test_files = _actual_test_files(target_root, plan)
    if not test_files:
        return []
    expected = _expected_test_symbols(plan)
    if len(expected) < 2:
        return []
    tokens: set[str] = set()
    test_paths: list[str] = []
    for relative_path, content in test_files:
        test_paths.append(relative_path)
        tokens.update(_identifier_tokens(content, suffix=Path(relative_path).suffix.lower()))
    covered = sorted(symbol for symbol in expected if symbol in tokens)
    required = _required_test_symbol_count(
        len(expected),
        validation_passed=validation_passed,
        explicit_api_obligations=bool(plan.api_obligations),
    )
    if len(covered) >= required:
        return []
    missing = sorted(symbol for symbol in expected if symbol not in tokens)
    test_label = ", ".join(test_paths[:3])
    return [
        "test coverage does not exercise public API obligations in "
        f"{test_label}: covered {len(covered)}/{len(expected)}, "
        f"required {required}; missing examples: {', '.join(missing[:6])}"
    ]


def _documentation_reference_errors(target_root: Path, plan: ProjectPlan) -> list[str]:
    errors: list[str] = []
    package_names = _package_names(plan)
    for relative_path, content in _actual_document_files(target_root, plan):
        missing = _missing_document_references(target_root, content, package_names=package_names)
        if missing:
            errors.append(f"documentation references missing file in {relative_path}: {', '.join(missing[:4])}")
    return errors


def _actual_test_files(target_root: Path, plan: ProjectPlan) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for relative_path in plan.required_paths():
        if not _looks_test_path(relative_path):
            continue
        path = target_root / relative_path
        content = _read_text(path)
        if content is not None:
            files.append((relative_path, content))
    return files


def _actual_document_files(target_root: Path, plan: ProjectPlan) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for relative_path in plan.required_paths():
        suffix = Path(relative_path).suffix.lower()
        if suffix not in {".md", ".rst", ".txt"}:
            continue
        path = target_root / relative_path
        content = _read_text(path)
        if content is not None:
            files.append((relative_path, content))
    return files


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _expected_test_symbols(plan: ProjectPlan) -> set[str]:
    symbols: set[str] = set()
    for names in planned_public_api_symbols(plan).values():
        for symbol in names:
            if symbol.startswith("__all__:"):
                symbol = symbol.split(":", 1)[1]
            if "." in symbol:
                owner, _, member = symbol.partition(".")
                symbols.add(owner)
                if len(member) > 2:
                    symbols.add(member)
                continue
            if len(symbol) > 2:
                symbols.add(symbol)
    return symbols


def _required_test_symbol_count(
    expected_count: int,
    *,
    validation_passed: bool = False,
    explicit_api_obligations: bool = False,
) -> int:
    if validation_passed and explicit_api_obligations:
        return 1
    if expected_count <= 2:
        return 1
    return min(3, max(2, expected_count // 3))


def _mentions_core_functionality(lowered_report: str) -> bool:
    return any(
        marker in lowered_report
        for marker in (
            "core functionality",
            "핵심 기능",
            "주요 기능",
            "주요 동작",
        )
    )


def _mentions_obligation_coverage(lowered_report: str) -> bool:
    return any(
        marker in lowered_report
        for marker in (
            "obligation coverage",
            "요구사항 충족",
            "의무 매트릭스",
            "커버리지 매트릭스",
        )
    )


def _identifier_tokens(content: str, *, suffix: str) -> set[str]:
    if suffix == ".py":
        try:
            module = ast.parse(content)
        except SyntaxError:
            return set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", content))
        tokens: set[str] = set()
        for node in ast.walk(module):
            if isinstance(node, ast.Name):
                tokens.add(node.id)
            elif isinstance(node, ast.Attribute):
                tokens.add(node.attr)
            elif isinstance(node, ast.alias):
                tokens.add((node.asname or node.name).split(".")[-1])
        return tokens
    return set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", content))


def _missing_document_references(target_root: Path, content: str, *, package_names: set[str]) -> list[str]:
    references: set[str] = set()
    references.update(_explicit_file_references(content))
    references.update(_module_file_references(content, package_names=package_names))
    missing: list[str] = []
    for reference in sorted(references):
        raw_reference = reference.replace("\\", "/")
        if raw_reference.startswith("/") or ".." in raw_reference.split("/"):
            continue
        normalized = raw_reference.lstrip("./")
        if not _reference_exists(target_root, normalized):
            missing.append(normalized)
    return missing


def _explicit_file_references(content: str) -> set[str]:
    references: set[str] = set()
    pattern = r"(?:`|\(|\s)(?P<path>\.?/?(?:[\w.-]+/)+[\w.-]+\.(?:py|js|ts|go|rs|java))(?=`|\)|\s|$)"
    for match in re.finditer(pattern, content):
        references.add(match.group("path"))
    tree_chars = ("├", "└", "│", "─")
    for line in content.splitlines():
        if not any(char in line for char in tree_chars):
            continue
        for match in re.finditer(r"\b(?P<path>[\w.-]+\.(?:py|js|ts|go|rs|java))\b", line):
            references.add(match.group("path"))
    return references


def _module_file_references(content: str, *, package_names: set[str]) -> set[str]:
    references: set[str] = set()
    if not package_names:
        return references
    module_pattern = r"\b(?P<module>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){1,})\b"
    for match in re.finditer(module_pattern, content):
        module = match.group("module")
        root = module.split(".", 1)[0]
        if root not in package_names:
            continue
        module_path = module.replace(".", "/") + ".py"
        references.add(f"src/{module_path}")
    return references


def _reference_exists(target_root: Path, reference: str) -> bool:
    path = target_root / reference
    if path.exists():
        return True
    if "/" not in reference:
        return any(candidate.is_file() for candidate in target_root.rglob(reference))
    if reference.endswith(".py"):
        init_reference = reference[:-3] + "/__init__.py"
        return (target_root / init_reference).exists()
    return False


def _package_names(plan: ProjectPlan) -> set[str]:
    names: set[str] = set()
    for relative_path in plan.required_paths():
        normalized = relative_path.replace("\\", "/")
        parts = normalized.split("/")
        if len(parts) >= 3 and parts[0] == "src" and parts[-1].endswith(".py"):
            names.add(parts[1])
        elif len(parts) >= 2 and parts[-1].endswith(".py") and parts[0] not in {"tests", "test"}:
            names.add(parts[0])
    return names


def _looks_test_path(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    name = Path(lowered).name
    return lowered.startswith("tests/") or "/tests/" in lowered or name.startswith("test_")

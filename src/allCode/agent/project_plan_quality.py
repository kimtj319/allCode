"""Quality checks for model-authored generation plans."""

from __future__ import annotations

import re
from pathlib import Path

from allCode.agent.api_obligation_checker import declared_public_api_symbols
from allCode.agent.task_plan import PlannedFile, ProjectPlan


def project_plan_quality_errors(plan: ProjectPlan, prompt: str = "") -> list[str]:
    """Return generic structural errors for a model-authored project plan.

    These checks intentionally avoid scenario names or prompt-specific escape
    hatches. They validate whether the plan's own obligations can plausibly be
    generated, exercised, and reported before the workflow starts writing
    files.
    """

    errors: list[str] = []
    if not plan.files:
        return ["project plan contains no files"]

    implementation_files = [file for file in plan.files if _is_implementation_file(file)]
    test_files = [file for file in plan.files if _is_test_file(file)]
    document_files = [file for file in plan.files if _is_document_file(file)]

    if implementation_files and _validation_implied(prompt, plan) and not plan.validation_commands:
        errors.append("project plan omits validation commands for a validation-required request")
    if implementation_files and _tests_implied(prompt, plan) and not test_files:
        errors.append("project plan omits tests for requested or declared behavior")
    if _documentation_implied(prompt, plan) and not document_files:
        errors.append("project plan omits requested documentation")

    errors.extend(_api_obligation_errors(plan, test_files))
    errors.extend(_weak_test_errors(plan, test_files))
    return errors


def _api_obligation_errors(plan: ProjectPlan, test_files: list[PlannedFile]) -> list[str]:
    if not plan.api_obligations:
        return []
    errors: list[str] = []
    # The obligation's target file must be in the plan, but we do NOT require the
    # symbol to be declared in the planner's (often skeleton) inline content: the
    # model editor generates the real implementation for each source/test file,
    # and the post-generation completion check validates obligations against the
    # final written files. Requiring inline declaration here would reject good
    # skeleton-first plans whose bodies are filled in downstream.
    planned_paths = {file.path for file in plan.files}
    for obligation in plan.api_obligations:
        if obligation.path not in planned_paths:
            errors.append(f"api obligation references a file not in the plan: {obligation.path}:{obligation.symbol}")
    expected = _contract_symbol_names({obligation.symbol for obligation in plan.api_obligations})
    if expected and not test_files:
        errors.append("api obligations have no planned test coverage")
        return errors
    if expected and test_files:
        test_tokens = _test_tokens(test_files)
        covered = {symbol for symbol in expected if symbol in test_tokens}
        required = 1 if len(expected) <= 2 else min(3, max(2, len(expected) // 3))
        if len(covered) < required:
            missing = ", ".join(sorted(expected - covered)[:6])
            errors.append(
                "api obligations are weakly covered by planned tests: "
                f"covered {len(covered)}/{len(expected)}, required {required}; missing examples: {missing}"
            )
    return errors


def _weak_test_errors(plan: ProjectPlan, test_files: list[PlannedFile]) -> list[str]:
    if not test_files:
        return []
    source_symbols = _contract_symbol_names(set().union(*declared_public_api_symbols(plan).values()))
    if len(source_symbols) < 3:
        return []
    test_tokens = _test_tokens(test_files)
    covered = {symbol for symbol in source_symbols if symbol in test_tokens}
    required = min(3, max(2, len(source_symbols) // 3))
    if len(covered) >= required:
        return []
    missing = ", ".join(sorted(source_symbols - covered)[:6])
    return [
        "planned tests are too thin for the public surface: "
        f"covered {len(covered)}/{len(source_symbols)}, required {required}; missing examples: {missing}"
    ]


def _is_implementation_file(file: PlannedFile) -> bool:
    if file.stage == "tests" or _is_test_file(file):
        return False
    return Path(file.path).suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs"}


def _is_test_file(file: PlannedFile) -> bool:
    path = file.path.replace("\\", "/").lower()
    name = path.rsplit("/", 1)[-1]
    return file.stage == "tests" or path.startswith("tests/") or "/tests/" in path or name.startswith("test_")


def _is_document_file(file: PlannedFile) -> bool:
    name = file.path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name in {"readme", "readme.md", "readme.rst"} or Path(name).suffix.lower() in {".md", ".rst", ".txt"}


def _validation_implied(prompt: str, plan: ProjectPlan) -> bool:
    lowered = prompt.lower()
    compact = re.sub(r"\s+", "", lowered)
    if plan.api_obligations:
        return True
    return any(term in lowered or term in compact for term in ("test", "validate", "pytest", "unit", "검증", "테스트"))


def _tests_implied(prompt: str, plan: ProjectPlan) -> bool:
    lowered = prompt.lower()
    compact = re.sub(r"\s+", "", lowered)
    if plan.api_obligations:
        return True
    return any(term in lowered or term in compact for term in ("test", "pytest", "unit test", "unittest", "테스트"))


def _documentation_implied(prompt: str, plan: ProjectPlan) -> bool:
    lowered = prompt.lower()
    compact = re.sub(r"\s+", "", lowered)
    if any(_is_document_file(file) for file in plan.files):
        return False
    return any(term in lowered or term in compact for term in ("readme", "documentation", "docs", "문서", "사용법"))


def _test_tokens(test_files: list[PlannedFile]) -> set[str]:
    tokens: set[str] = set()
    for file in test_files:
        tokens.update(_identifier_tokens(file.content))
    return tokens


def _identifier_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text) if len(token) > 2}


def _contract_symbol_names(symbols: set[str]) -> set[str]:
    names: set[str] = set()
    for symbol in symbols:
        if symbol.startswith("__all__:"):
            symbol = symbol.split(":", 1)[1]
        if "." in symbol:
            owner, _, member = symbol.partition(".")
            names.add(owner)
            if len(member) > 2:
                names.add(member)
            continue
        if len(symbol) > 2:
            names.add(symbol)
    return names


def _symbol_matches(actual: str, expected: str) -> bool:
    return actual == expected or actual.endswith(f".{expected}") or expected.endswith(f".{actual}")

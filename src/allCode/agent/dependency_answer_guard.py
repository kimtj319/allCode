"""Soft answer guard for user-requested dependency constraints."""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from typing import Iterable

from allCode.agent.prompt_constraint_terms import COMMON_WORKSPACE_DIRS
from allCode.core.models import Message

THIRD_PARTY_TERMS = (
    "pytest",
    "requests",
    "click",
    "typer",
    "rich",
    "pydantic",
    "numpy",
    "pandas",
    "fastapi",
    "flask",
    "django",
    "sqlalchemy",
    "httpx",
    "aiohttp",
)

INSTALL_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_.-])pip\s+install(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])uv\s+add(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])poetry\s+add(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])pipenv\s+install(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])npm\s+install(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])yarn\s+add(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])pnpm\s+add(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])bun\s+add(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])go\s+get(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])cargo\s+add(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])requirements\.txt(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])pyproject\.toml(?![A-Za-z0-9_.-]).{0,80}(?<![A-Za-z0-9_.-])dependencies(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])package\.json(?![A-Za-z0-9_.-]).{0,80}(?<![A-Za-z0-9_.-])dependencies(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])go\.mod(?![A-Za-z0-9_.-]).{0,80}(?<![A-Za-z0-9_.-])require(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])Cargo\.toml(?![A-Za-z0-9_.-]).{0,80}(?<![A-Za-z0-9_.-])dependencies(?![A-Za-z0-9_.-])", re.IGNORECASE),
)
FENCED_BLOCK_PATTERN = re.compile(r"```(?P<lang>[A-Za-z0-9_+.-]*)[^\n]*\n(?P<code>.*?)```", re.DOTALL)
ANSWER_PATH_PATTERN = re.compile(r"`?(?P<path>(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.py)`?")
PYTHON_STDLIB_MODULES = frozenset(
    set(getattr(sys, "stdlib_module_names", ()))
    | set(sys.builtin_module_names)
    | {
        "__future__",
        "argparse",
        "asyncio",
        "collections",
        "dataclasses",
        "datetime",
        "functools",
        "html",
        "http",
        "importlib",
        "json",
        "pathlib",
        "re",
        "sqlite3",
        "subprocess",
        "sys",
        "tempfile",
        "typing",
        "unittest",
        "urllib",
    }
)

ENGLISH_PREFIX_NEGATION_MARKERS = (
    "do not",
    "don't",
    "avoid",
    "instead of",
    "without",
    "no ",
    "not use",
)

TERM_SUFFIX_REJECTION_MARKERS = (
    "should not",
    "not recommended",
    "사용하지",
    "쓰지",
    "피하",
    "금지",
    "대신",
    "없이",
    "불필요",
    "실행하지",
    "하지 말",
)


@dataclass(frozen=True)
class DependencyAnswerViolation:
    reason: str
    excerpt: str


def dependency_answer_violation(*, answer: str, routing) -> DependencyAnswerViolation | None:
    """Return a violation when a direct answer conflicts with dependency constraints."""

    if getattr(routing, "kind", "") != "answer":
        return None
    flags = set(getattr(routing, "flags", set()) or set())
    if "stdlib_only_requested" not in flags:
        return None
    if not ({"answer_artifact", "code_artifact"} & flags):
        return None
    for line in _meaningful_lines(answer):
        lowered = line.lower()
        if _line_has_positive_install_command(line):
            return DependencyAnswerViolation("dependency_constraint_install_suggestion", _excerpt(line))
        for term in THIRD_PARTY_TERMS:
            match = _ascii_token_match(lowered, term)
            if match is None:
                continue
            if _term_is_rejected_or_negated(lowered, start=match.start(), end=match.end()):
                continue
            return DependencyAnswerViolation("dependency_constraint_third_party_package", _excerpt(line))
    local_roots = _local_package_roots(answer)
    for module in _python_import_violations(answer, local_roots=local_roots):
        return DependencyAnswerViolation(
            "dependency_constraint_non_stdlib_import",
            f"non-stdlib import: {module}",
        )
    return None


def dependency_answer_retry_used(recovery, *, max_attempts: int = 1) -> bool:
    states = getattr(recovery, "states", []) or []
    count = sum(1 for item in states if getattr(item, "reason", "") == "dependency_constraint_violation")
    return count >= max_attempts


def dependency_answer_retry_messages(
    *,
    current_messages: list[Message],
    previous_answer: str,
    violation: DependencyAnswerViolation,
    language: str,
) -> list[Message]:
    if language == "ko":
        prompt = "\n".join(
            [
                "이전 답변은 사용자가 요청한 표준 라이브러리 전용/외부 의존성 금지 제약을 위반했습니다.",
                f"위반 근거: {violation.reason}: {violation.excerpt}",
                "외부 패키지, pip install, requirements 의존성, pytest 같은 서드파티 테스트 도구를 제안하지 마십시오.",
                "Python 예시는 argparse/json/pathlib/sqlite3/unittest/tempfile/subprocess 같은 표준 라이브러리만 사용해 다시 답변하십시오.",
                "이전 답변의 유용한 설계와 코드는 유지하되 위반 줄만 제거하거나 표준 라이브러리 대안으로 교체하십시오.",
                "JSON이나 위반 메타데이터를 출력하지 말고, 사용자 요청과 같은 언어로 최종 답변만 작성하십시오.",
            ]
        )
    else:
        prompt = "\n".join(
            [
                "The previous answer violated the user's standard-library-only/no-third-party-dependency constraint.",
                f"Violation evidence: {violation.reason}: {violation.excerpt}",
                "Do not suggest external packages, pip install commands, dependency files, or third-party test tools such as pytest.",
                "For Python examples, use only standard-library modules such as argparse, json, pathlib, sqlite3, unittest, tempfile, and subprocess.",
                "Preserve useful design and code from the previous answer, but remove or replace only the violating lines.",
                "Do not output JSON or violation metadata; write only the final answer in the user's language.",
            ]
        )
    messages = list(current_messages)
    messages.append(Message(role="assistant", content=previous_answer.rstrip()))
    messages.append(Message(role="user", content=prompt))
    return messages


def dependency_answer_blocked_message(*, violation: DependencyAnswerViolation, language: str) -> str:
    if language == "ko":
        return "\n".join(
            [
                "요청한 표준 라이브러리 전용 제약을 만족하는 최종 답변을 만들지 못했습니다.",
                f"마지막 위반 근거: {violation.reason}: {violation.excerpt}",
                "외부 패키지 제안을 제거한 뒤 다시 요청해 주세요.",
            ]
        )
    return "\n".join(
        [
            "I could not produce a final answer that satisfies the standard-library-only constraint.",
            f"Last violation: {violation.reason}: {violation.excerpt}",
            "Please retry after removing third-party package suggestions.",
        ]
    )


def dependency_answer_sanitized_fallback(
    *,
    messages: list[Message],
    current_answer: str,
    routing,
    language: str,
) -> str:
    """Return the best previous answer with dependency-violating lines removed."""

    for candidate in _candidate_answers(messages, current_answer):
        cleaned = _strip_dependency_violation_lines(candidate)
        if len(cleaned) < 120:
            continue
        if dependency_answer_violation(answer=cleaned, routing=routing) is not None:
            continue
        note = (
            "외부 의존성 제약을 지키기 위해 패키지 설치나 서드파티 도구 제안으로 보이는 줄은 제거했습니다."
            if language == "ko"
            else "I removed lines that appeared to recommend package installation or third-party tools to honor the dependency constraint."
        )
        return f"{cleaned.rstrip()}\n\n{note}"
    return ""


def _meaningful_lines(answer: str) -> Iterable[str]:
    for raw in str(answer or "").splitlines():
        line = raw.strip()
        if line:
            yield line


def _candidate_answers(messages: list[Message], current_answer: str) -> Iterable[str]:
    if current_answer:
        yield current_answer
    for message in reversed(messages):
        if message.role == "assistant" and message.content:
            yield message.content


def _strip_dependency_violation_lines(answer: str) -> str:
    kept: list[str] = []
    for raw in str(answer or "").splitlines():
        line = raw.rstrip()
        if not _line_has_dependency_violation(line):
            kept.append(line)
    return "\n".join(kept).strip()


def _line_has_dependency_violation(line: str) -> bool:
    lowered = line.lower()
    if _line_has_positive_install_command(line):
        return True
    for term in THIRD_PARTY_TERMS:
        match = _ascii_token_match(lowered, term)
        if match is not None and not _term_is_rejected_or_negated(lowered, start=match.start(), end=match.end()):
            return True
    return False


def _line_has_positive_install_command(line: str) -> bool:
    lowered = line.lower()
    for pattern in INSTALL_PATTERNS:
        match = pattern.search(line)
        if match is None:
            continue
        if _term_is_rejected_or_negated(lowered, start=match.start(), end=match.end()):
            continue
        return True
    return False


def _python_import_violations(answer: str, *, local_roots: set[str]) -> Iterable[str]:
    for code in _extract_python_code_blocks(answer):
        for module in _imported_modules(code):
            top_level = module.split(".", 1)[0]
            if _allowed_python_import(top_level, local_roots=local_roots):
                continue
            yield top_level


def _extract_python_code_blocks(answer: str) -> Iterable[str]:
    found = False
    for match in FENCED_BLOCK_PATTERN.finditer(str(answer or "")):
        lang = match.group("lang").strip().lower()
        code = match.group("code")
        if lang in {"", "python", "py", "python3"} and _looks_like_python_import_block(code):
            found = True
            yield code
    if not found:
        import_lines = [
            line
            for line in str(answer or "").splitlines()
            if re.match(r"\s*(?:from\s+[A-Za-z_][A-Za-z0-9_.]*\s+import|import\s+[A-Za-z_][A-Za-z0-9_.]*)", line)
        ]
        if import_lines:
            yield "\n".join(import_lines)


def _looks_like_python_import_block(code: str) -> bool:
    return bool(re.search(r"^\s*(?:from\s+[A-Za-z_][A-Za-z0-9_.]*\s+import|import\s+[A-Za-z_][A-Za-z0-9_.]*)", code, re.MULTILINE))


def _imported_modules(code: str) -> Iterable[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names if alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                modules.append(node.module)
        elif isinstance(node, ast.Call):
            dynamic = _dynamic_import_module(node)
            if dynamic:
                modules.append(dynamic)
    return modules


def _dynamic_import_module(node: ast.Call) -> str:
    function = node.func
    is_importlib_call = (
        isinstance(function, ast.Attribute)
        and function.attr == "import_module"
        and isinstance(function.value, ast.Name)
        and function.value.id == "importlib"
    )
    is_builtin_import = isinstance(function, ast.Name) and function.id == "__import__"
    if not (is_importlib_call or is_builtin_import):
        return ""
    if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
        return ""
    return node.args[0].value


def _allowed_python_import(top_level: str, *, local_roots: set[str]) -> bool:
    normalized = top_level.strip().replace("-", "_")
    if not normalized:
        return True
    if normalized in PYTHON_STDLIB_MODULES:
        return True
    return normalized in local_roots


def _local_package_roots(answer: str) -> set[str]:
    roots: set[str] = set()
    workspace_dirs = {item.replace("\\", "/") for item in COMMON_WORKSPACE_DIRS}
    for match in ANSWER_PATH_PATTERN.finditer(str(answer or "")):
        path = match.group("path").strip().strip("`").replace("\\", "/")
        parts = [part for part in path.split("/") if part]
        if not parts:
            continue
        root = parts[0]
        if root in workspace_dirs and len(parts) > 1:
            root = parts[1]
        if root:
            roots.add(root.replace("-", "_"))
    return roots


def _term_is_rejected_or_negated(lowered_line: str, *, start: int, end: int) -> bool:
    prefix = lowered_line[max(0, start - 36) : start]
    suffix = lowered_line[end : end + 36]
    if any(marker in prefix for marker in ENGLISH_PREFIX_NEGATION_MARKERS):
        return True
    return any(marker in suffix for marker in TERM_SUFFIX_REJECTION_MARKERS)


def _excerpt(line: str, *, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", line).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _ascii_token_match(text: str, token: str) -> re.Match[str] | None:
    return re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(token)}(?![A-Za-z0-9_.-])", text)

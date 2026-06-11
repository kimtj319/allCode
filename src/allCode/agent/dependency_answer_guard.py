"""Soft answer guard for user-requested dependency constraints."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

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
    re.compile(r"(?<![A-Za-z0-9_.-])requirements\.txt(?![A-Za-z0-9_.-])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])pyproject\.toml(?![A-Za-z0-9_.-]).{0,80}(?<![A-Za-z0-9_.-])dependencies(?![A-Za-z0-9_.-])", re.IGNORECASE),
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
        if any(pattern.search(line) for pattern in INSTALL_PATTERNS):
            return DependencyAnswerViolation("dependency_constraint_install_suggestion", _excerpt(line))
        for term in THIRD_PARTY_TERMS:
            match = _ascii_token_match(lowered, term)
            if match is None:
                continue
            if _term_is_rejected_or_negated(lowered, start=match.start(), end=match.end()):
                continue
            return DependencyAnswerViolation("dependency_constraint_third_party_package", _excerpt(line))
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
    if any(pattern.search(line) for pattern in INSTALL_PATTERNS):
        return True
    for term in THIRD_PARTY_TERMS:
        match = _ascii_token_match(lowered, term)
        if match is not None and not _term_is_rejected_or_negated(lowered, start=match.start(), end=match.end()):
            return True
    return False


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

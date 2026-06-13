"""Shared prompt path and follow-up reference parsing."""

from __future__ import annotations

import re
from pathlib import Path


def looks_like_test_path(path: str) -> bool:
    """True for paths under a tests/ directory or with a test_ filename prefix."""
    lowered = path.lower().replace("\\", "/")
    name = Path(lowered).name
    return lowered.startswith("tests/") or "/tests/" in lowered or name.startswith("test_")


PATH_PATTERN = re.compile(
    r"(?:@)?(?P<path>(?:\.{1,2}/|/)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.@+-]+)+|[A-Za-z0-9_.-]+\.(?:py|js|ts|tsx|java|go|rs|md|toml|yaml|yml|json|txt))"
)

FOLLOWUP_TERMS = (
    "that file",
    "that function",
    "same file",
    "same function",
    "그 파일",
    "그 함수",
    "해당 파일",
    "해당 함수",
    "방금",
    "앞서",
    "앞 문서",
    "앞문서",
    "이전 답변",
    "앞선 답변",
    "방금 답변",
    "previous answer",
    "previous response",
)


def extract_prompt_path(prompt: str) -> str | None:
    match = PATH_PATTERN.search(prompt)
    if match:
        return match.group("path").lstrip("@")
    return None


def extract_prompt_paths(prompt: str) -> list[str]:
    paths: list[str] = []
    for match in PATH_PATTERN.finditer(prompt):
        path = match.group("path").lstrip("@")
        if path and path not in paths:
            paths.append(path)
    return paths


def is_followup_reference(prompt: str) -> bool:
    lowered = prompt.lower()
    return any(term in lowered for term in FOLLOWUP_TERMS)

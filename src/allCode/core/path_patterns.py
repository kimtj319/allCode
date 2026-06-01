"""Shared prompt path and follow-up reference parsing."""

from __future__ import annotations

import re

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
)


def extract_prompt_path(prompt: str) -> str | None:
    match = PATH_PATTERN.search(prompt)
    if match:
        return match.group("path").lstrip("@")
    return None


def is_followup_reference(prompt: str) -> bool:
    lowered = prompt.lower()
    return any(term in lowered for term in FOLLOWUP_TERMS)

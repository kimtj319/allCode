"""Shared prompt safety signals for routing and constraints."""

from __future__ import annotations

import re
from collections.abc import Sequence

READ_ONLY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:코드\s*)?(?:파일\s*)?(?:수정|변경|편집|삭제|작성|생성)"
        r"(?:은|는|이|가|도|만)?\s*(?:절대\s*)?(?:엄격히\s*)?"
        r"(?:금지|불가|하지\s*마|하지마|하지\s*말|하지말|마라|않)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:do\s+not|don't|never)\s+(?:modify|edit|change|update|delete|write|create)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:read[- ]only|analysis\s+only|inspect\s+only|no\s+(?:file\s+)?changes?)",
        re.IGNORECASE,
    ),
)

_CLAUSE_SPLIT_RE = re.compile(r"[\n\r.!?。！？;；]+")
_READ_ONLY_MUTATION_TOKENS = (
    "수정",
    "변경",
    "편집",
    "삭제",
    "제거",
    "작성",
    "생성",
    "커밋",
    "포맷",
    "포맷팅",
    "파일변경",
    "파일생성",
    "edit",
    "modify",
    "change",
    "write",
    "create",
    "delete",
    "remove",
    "commit",
    "format",
)
_READ_ONLY_NEGATION_TOKENS = (
    "금지",
    "불가",
    "하지마",
    "하지말",
    "하지마라",
    "하지않",
    "안됨",
    "안됌",
    "안되",
    "안돼",
    "mustnot",
    "donot",
    "don't",
    "never",
)


def read_only_pattern_matched(prompt: str) -> bool:
    """Return true when the prompt contains a generic no-mutation constraint."""

    return any(pattern.search(prompt) for pattern in READ_ONLY_PATTERNS) or read_only_clause_matched(prompt)


def read_only_clause_matched(prompt: str) -> bool:
    """Detect list-style no-mutation clauses without matching a specific prompt."""

    for clause in _CLAUSE_SPLIT_RE.split(prompt):
        compact = re.sub(r"\s+", "", clause).lower()
        if not compact:
            continue
        if _contains_any(compact, _READ_ONLY_MUTATION_TOKENS) and _contains_any(compact, _READ_ONLY_NEGATION_TOKENS):
            return True
    return False


def _contains_any(text: str, tokens: Sequence[str]) -> bool:
    return any(token.lower().replace(" ", "") in text for token in tokens)


def append_marker_if_matched(matched: list[str], marker: str, *, condition: bool) -> None:
    if condition and marker not in matched:
        matched.append(marker)


def has_any_term(
    terms: Sequence[str],
    *,
    prompt: str,
    lowered: str,
    compact: str | None = None,
    compact_match: bool = False,
    matched: list[str] | None = None,
) -> bool:
    haystack = (compact or re.sub(r"\s+", "", prompt)).lower() if compact_match else lowered
    found = [
        term for term in terms if (term.lower().replace(" ", "") if compact_match else term.lower()) in haystack
    ]
    if matched is not None:
        matched.extend(found)
    return bool(found)

"""Prompt/path artifact detection helpers used by phase gates."""

from __future__ import annotations

from pathlib import Path
import re


def looks_like_test_artifact(path: str, *, workspace_root: str) -> bool:
    try:
        candidate = Path(path).resolve()
        root = Path(workspace_root).resolve()
        relative = candidate.relative_to(root).as_posix().lower()
    except (OSError, ValueError):
        relative = Path(path).as_posix().lower()
    parts = [part for part in relative.split("/") if part]
    if any(part in {"test", "tests", "__tests__"} for part in parts[:-1]):
        return True
    name = parts[-1] if parts else relative
    if name in {"test.py", "tests.py"}:
        return True
    return (
        name.startswith("test_")
        or name.endswith(("_test.py", "_test.go", ".test.js", ".test.ts", ".test.tsx", ".spec.js", ".spec.ts", ".spec.tsx"))
        or "spec" in name
    )


def prompt_requests_tests(prompt: str) -> bool:
    lowered = prompt.lower()
    compact = prompt.replace(" ", "")
    english_patterns = (
        r"\b(?:add|write|create|update|implement|include)\s+(?:unit\s+)?tests?\b",
        r"\btests?\s+(?:for|covering|that\s+cover)\b",
    )
    if any(re.search(pattern, lowered) for pattern in english_patterns):
        return True
    korean_patterns = (
        "테스트도추가",
        "테스트를추가",
        "테스트추가",
        "테스트포함",
        "테스트를포함",
        "테스트도포함",
        "테스트도작성",
        "테스트를작성",
        "테스트작성",
        "테스트도만들",
        "테스트를만들",
        "테스트로만들",
        "테스트만들",
        "테스트를나눠",
        "테스트로나눠",
        "테스트분리",
        "테스트도보강",
        "테스트를보강",
        "테스트보강",
        "관련테스트를추가",
    )
    if any(marker in compact for marker in korean_patterns):
        return True
    return "테스트" in compact and any(marker in compact for marker in ("추가", "작성", "포함", "만들", "보강", "나눠", "분리"))


def prompt_requests_documents(prompt: str) -> bool:
    lowered = prompt.lower()
    compact = prompt.replace(" ", "").lower()
    english_patterns = (
        r"\b(?:add|write|create|update|include)\s+(?:a\s+)?(?:readme|docs?|documentation|usage guide)\b",
        r"\b(?:readme|docs?|documentation|usage guide)\s+(?:for|that|with|including)\b",
    )
    if any(re.search(pattern, lowered) for pattern in english_patterns):
        return True
    korean_markers = (
        "readme포함",
        "readme를포함",
        "readme작성",
        "readme를작성",
        "문서포함",
        "문서를포함",
        "문서작성",
        "문서를작성",
        "사용법포함",
        "사용법을포함",
        "사용법작성",
        "사용법을작성",
    )
    if any(marker in compact for marker in korean_markers):
        return True
    return any(term in compact for term in ("readme", "문서", "사용법")) and any(
        marker in compact for marker in ("추가", "작성", "포함", "만들", "생성")
    )

"""Auto-retrieve file:line grounding for codebase-analysis (inspect) turns.

Weak open models (e.g. gpt-oss-120b) tend to answer "how/where is X implemented"
from a generic package summary instead of reading and citing real files — the
biggest measured gap vs codex, whose answers anchor every claim to `file.py:line`.

For read-only inspection turns this proactively searches the workspace for the
identifiers/keywords the prompt mentions and injects the top `path:line: snippet`
matches as context, so the model can synthesize a grounded, citable answer.

Design: purely ADDITIVE context (never blocks, never mutates), bounded in size,
and a complete no-op when nothing relevant is found — so it cannot regress the
loop the way a hard gate could.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

# Identifier-ish tokens worth searching: snake_case, CamelCase, dotted module
# paths, or anything the user explicitly quoted in backticks.
_BACKTICK = re.compile(r"`([^`]+)`")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:[./][A-Za-z0-9_]+)+|[A-Za-z]+_[A-Za-z0-9_]+|[a-z]+[A-Z][A-Za-z0-9]+")

# Common Korean functional terms → English code keywords, so a natural-language
# prompt ("응답을 파싱하는 코드") still maps to the right symbols (parser).
_KO_KEYWORDS = {
    "파싱": ["parse", "parser"],
    "파서": ["parser"],
    "설정": ["config"],
    "세션": ["session"],
    "도구": ["tool"],
    "검증": ["valid", "test"],
    "라우팅": ["rout"],
    "라우터": ["router"],
    "완료": ["complet", "finaliz"],
    "프롬프트": ["prompt"],
    "메모리": ["memory"],
    "어댑터": ["adapter"],
    "스트리밍": ["stream"],
    "정책": ["policy"],
    "승인": ["approval"],
    "워크스페이스": ["workspace"],
    "인덱싱": ["index"],
    "구문": ["syntax"],
    "진입점": ["__main__", "main"],
    "엔트리": ["__main__", "main"],
    "테스트": ["test"],
    "오케스트": ["orchestr"],
}

_STOP = {
    "code", "this", "that", "with", "from", "into", "your", "what", "which",
    "where", "when", "how", "the", "and", "for", "are", "is", "of", "in",
}


def _candidate_terms(prompt: str) -> list[str]:
    terms: list[str] = []
    for m in _BACKTICK.finditer(prompt):
        terms.append(m.group(1).strip())
    for m in _IDENT.finditer(prompt):
        terms.append(m.group(0))
    for ko, eng in _KO_KEYWORDS.items():
        if ko in prompt:
            terms.extend(eng)
    # Normalize/dedupe; drop trivial or stopword tokens.
    seen: list[str] = []
    for t in terms:
        t = t.strip().strip(".,()[]{}:`\"'")
        if len(t) < 3 or t.lower() in _STOP:
            continue
        if t not in seen:
            seen.append(t)
    return seen[:8]


def _search_root(workspace_root: str) -> Path | None:
    root = Path(workspace_root)
    if not root.is_dir():
        return None
    src = root / "src"
    return src if src.is_dir() else root


def build_grounding_context(prompt: str, workspace_root: str, *, max_lines: int = 12) -> str | None:
    """Return an injectable grounding block, or None when nothing useful is found."""
    if not shutil.which("rg"):
        return None
    root = _search_root(workspace_root)
    if root is None:
        return None
    terms = _candidate_terms(prompt)
    if not terms:
        return None
    scored: list[tuple[int, str]] = []  # (score, "rel:line: snippet")
    seen: set[str] = set()
    for term in terms:
        try:
            proc = subprocess.run(
                ["rg", "-n", "--no-heading", "-S", "-m", "8", "-g", "*.py",
                 rf"(def|class)\s+\w*{re.escape(term)}|{re.escape(term)}", str(root)],
                capture_output=True, text=True, timeout=8,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        term_l = term.lower()
        for line in proc.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            path, lineno, content = parts
            try:
                rel = str(Path(path).relative_to(Path(workspace_root)))
            except ValueError:
                rel = path
            key = f"{rel}:{lineno}"
            if key in seen:
                continue
            stripped = content.strip()
            # Rank: a file whose path names the term, and an actual def/class
            # definition, are the relevant anchors — surface them first.
            score = 0
            if term_l in Path(rel).name.lower():
                score += 3
            if re.match(rf"\s*(def|class)\s+\w*{re.escape(term)}", content, re.IGNORECASE):
                score += 2
            elif stripped.startswith(("def ", "class ")):
                score += 1
            seen.add(key)
            scored.append((score, f"{rel}:{lineno}: {stripped[:120]}"))
    if not scored:
        return None
    scored.sort(key=lambda s: s[0], reverse=True)
    # Take top-scoring, capped at 2 lines per file for breadth.
    body_lines: list[str] = []
    per_file: dict[str, int] = {}
    for _score, entry in scored:
        rel = entry.split(":", 1)[0]
        if per_file.get(rel, 0) >= 2:
            continue
        per_file[rel] = per_file.get(rel, 0) + 1
        body_lines.append(entry)
        if len(body_lines) >= max_lines:
            break
    body = "\n".join(body_lines)
    return (
        "[자동 코드 검색 근거 / auto-retrieved code references] "
        "질문에 언급된 식별자를 워크스페이스에서 검색한 실제 위치입니다. "
        "답변의 각 주장은 아래 같은 `파일:줄` 근거에 기반해 작성하고 인용하세요. "
        "필요하면 read_file로 더 확인하되, 일반적인 패키지 요약만으로 답하지 마세요:\n"
        f"{body}"
    )

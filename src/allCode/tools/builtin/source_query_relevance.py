"""Query relevance helpers for bounded source representative ranking."""

from __future__ import annotations

import re
from pathlib import Path

from allCode.memory.schema import RepoMapEntry

KOREAN_TECH_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("소스", ("source", "code", "overview", "probe")),
    ("코드", ("code", "source", "module")),
    ("분석", ("analysis", "inspect", "overview")),
    ("답변", ("answer", "response", "final", "report", "synthesis")),
    ("최종", ("final", "answer", "report")),
    ("흐름", ("flow", "sequence", "runner", "loop", "orchestrator", "round", "handler")),
    ("연결", ("edge", "graph", "wiring", "import", "reference", "flow")),
    ("근거", ("evidence", "brief", "observation", "grounding")),
    ("확인", ("check", "grounding", "evidence")),
    ("컨텍스트", ("context", "prompt", "memory")),
    ("도구", ("tool", "executor", "registry", "processor")),
    ("라우팅", ("router", "route", "intent", "policy")),
    ("정책", ("policy", "approval", "safety")),
    ("검증", ("validation", "test", "repair")),
    ("수리", ("repair", "recovery", "validation")),
    ("생성", ("generation", "workflow", "plan", "project")),
    ("만들", ("build", "builder", "synthesis", "render", "final")),
    ("작성", ("write", "render", "synthesis", "answer", "report")),
    ("파일", ("file", "path", "target")),
    ("역할", ("role", "package", "module")),
    ("메모리", ("memory", "context", "session")),
)

ENGLISH_TECH_ALIASES: dict[str, tuple[str, ...]] = {
    "analysis": ("inspect", "overview", "source"),
    "answer": ("final", "response", "report", "synthesis"),
    "final": ("answer", "report"),
    "flow": ("runner", "loop", "orchestrator", "sequence"),
    "connection": ("edge", "graph", "wiring", "import", "reference"),
    "tool": ("executor", "registry", "processor"),
    "routing": ("router", "route", "intent", "policy"),
    "validation": ("test", "repair"),
    "repair": ("recovery", "validation"),
    "context": ("prompt", "memory"),
}

STOP_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "src",
}


def query_relevance_tokens(query: str) -> set[str]:
    """Return generic architecture tokens inferred from the user query.

    The mapping is intentionally domain-generic. It does not inspect scenario
    IDs, exact prompts, project names, or repository-specific paths.
    """

    if not query.strip():
        return set()
    tokens: set[str] = set()
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9_\\-]*|[0-9]+|[가-힣]+", query.lower()):
        for token in _identifier_tokens(raw):
            if token and token not in STOP_TOKENS and len(token) > 1:
                tokens.add(token)
                tokens.update(ENGLISH_TECH_ALIASES.get(token, ()))
        for marker, aliases in KOREAN_TECH_ALIASES:
            if marker in raw:
                tokens.update(aliases)
    return tokens


def query_relevance_score(entry: RepoMapEntry, query_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    path_overlap = _path_tokens(entry.path) & query_tokens
    symbol_overlap = _symbol_tokens(entry) & query_tokens
    import_overlap = _import_tokens(entry) & query_tokens
    score = 0.0
    score += min(len(path_overlap), 5) * 1.6
    score += min(len(symbol_overlap), 5) * 1.0
    score += min(len(import_overlap), 3) * 0.5
    return min(score, 9.0)


def path_query_relevance_score(path: str, query_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    return min(len(_path_tokens(path) & query_tokens) * 1.6, 8.0)


def path_relevance_tokens(path: str) -> set[str]:
    return _path_tokens(path)


def entry_relevance_tokens(entry: RepoMapEntry) -> set[str]:
    return _path_tokens(entry.path) | _symbol_tokens(entry) | _import_tokens(entry)


def query_relevance_matches(entry: RepoMapEntry, query_tokens: set[str]) -> list[str]:
    if not query_tokens:
        return []
    matched = sorted((_path_tokens(entry.path) | _symbol_tokens(entry) | _import_tokens(entry)) & query_tokens)
    return matched[:8]


def _path_tokens(path: str) -> set[str]:
    tokens: set[str] = set()
    for part in Path(path).with_suffix("").parts:
        tokens.update(_identifier_tokens(part.lower()))
    return _without_stop_tokens(tokens)


def _symbol_tokens(entry: RepoMapEntry) -> set[str]:
    tokens: set[str] = set()
    for definition in entry.definitions:
        tokens.update(_identifier_tokens(definition.lower()))
    for symbol in entry.symbols:
        if isinstance(symbol, dict):
            for key in ("name", "qualified_name", "kind"):
                value = symbol.get(key)
                if value:
                    tokens.update(_identifier_tokens(str(value).lower()))
    return _without_stop_tokens(tokens)


def _import_tokens(entry: RepoMapEntry) -> set[str]:
    tokens: set[str] = set()
    for imported in entry.imports:
        tokens.update(_identifier_tokens(str(imported).lower()))
    return _without_stop_tokens(tokens)


def _identifier_tokens(value: str) -> set[str]:
    pieces: set[str] = set()
    for chunk in re.split(r"[^A-Za-z0-9가-힣]+", value):
        if not chunk:
            continue
        pieces.add(chunk)
        pieces.update(part for part in re.split(r"[_\\-]+", chunk) if part)
        pieces.update(_camel_parts(chunk))
    return pieces


def _camel_parts(value: str) -> set[str]:
    if not re.search(r"[A-Z]", value):
        return set()
    return {part.lower() for part in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+", value)}


def _without_stop_tokens(tokens: set[str]) -> set[str]:
    return {token for token in tokens if len(token) > 1 and token not in STOP_TOKENS}

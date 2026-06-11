"""Architecture role helpers for representative source ranking."""

from __future__ import annotations

from pathlib import Path

from allCode.memory.schema import RepoMapEntry
from allCode.tools.builtin.source_query_relevance import path_relevance_tokens, query_relevance_score

ARCHITECTURE_NAME_HINTS = (
    "loop",
    "runner",
    "router",
    "workflow",
    "registry",
    "executor",
    "manager",
    "service",
    "client",
    "parser",
    "schema",
    "models",
    "events",
    "indexer",
    "store",
    "runtime",
)
ARCHITECTURE_ROLE_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("routing", ("router", "route", "intent", "policy")),
    ("loop-orchestration", ("loop", "runner", "runtime", "orchestrator", "round", "handler")),
    ("source-analysis", ("source", "analysis", "overview", "probe", "inspect", "grounding")),
    ("answer-synthesis", ("answer", "final", "report", "synthesis", "brief", "response", "fallback")),
    ("prompt-context", ("prompt", "context", "constraint")),
    ("recovery-validation", ("recovery", "validation", "repair")),
    ("workflow-plan", ("workflow", "plan", "task")),
    ("tool", ("tool", "executor", "registry", "processor")),
)


def architecture_filename_score(path: str) -> float:
    stem = Path(path).stem.lower()
    if stem in ARCHITECTURE_NAME_HINTS:
        return 1.8
    if any(hint in stem.split("_") or hint in stem.split("-") for hint in ARCHITECTURE_NAME_HINTS):
        return 1.2
    return 0.0


def architecture_diversity_candidates(
    entries: list[RepoMapEntry],
    *,
    scores: dict[str, float],
    selected: list[str],
    query_tokens: set[str],
) -> list[RepoMapEntry]:
    candidates: list[RepoMapEntry] = []
    selected_paths = set(selected)
    relevant_bucket_exists = any(
        _bucket_query_relevance(markers, query_tokens) > 0 for _bucket, markers in ARCHITECTURE_ROLE_BUCKETS
    )
    for _bucket, markers in ARCHITECTURE_ROLE_BUCKETS:
        bucket_relevance = _bucket_query_relevance(markers, query_tokens)
        if relevant_bucket_exists and bucket_relevance <= 0:
            continue
        bucket_candidates = [
            entry for entry in entries if entry.path not in selected_paths and _bucket_strength(entry.path, markers) > 0
        ]
        if not bucket_candidates:
            continue
        best = max(
            bucket_candidates,
            key=lambda item: (
                bucket_relevance,
                _bucket_strength(item.path, markers),
                query_relevance_score(item, query_tokens),
                scores.get(item.path, 0.0),
                -_helper_penalty(item.path),
                -len(item.path),
            ),
        )
        candidates.append(best)
        selected_paths.add(best.path)
    return candidates


def query_relevant_candidates(
    entries: list[RepoMapEntry],
    *,
    scores: dict[str, float],
    selected: list[str],
    query_tokens: set[str],
) -> list[RepoMapEntry]:
    if not query_tokens:
        return []
    selected_paths = set(selected)
    candidates = [
        entry for entry in entries if entry.path not in selected_paths and query_relevance_score(entry, query_tokens) > 0
    ]
    return sorted(
        candidates,
        key=lambda item: (
            query_relevance_score(item, query_tokens),
            _focused_query_priority(item, query_tokens),
            architecture_filename_score(item.path),
            scores.get(item.path, 0.0),
            -_helper_penalty(item.path),
            -len(item.path),
        ),
        reverse=True,
    )


def _focused_query_priority(entry: RepoMapEntry, query_tokens: set[str]) -> int:
    path_tokens = path_relevance_tokens(entry.path)
    priority = 0
    if query_tokens & {"answer", "final", "brief", "synthesis", "response", "report", "build", "render"}:
        priority += len(path_tokens & {"answer", "final", "brief", "synthesis", "response", "fallback", "render"})
    if query_tokens & {"source", "analysis", "inspect", "overview", "probe", "grounding"}:
        priority += len(path_tokens & {"source", "analysis", "inspect", "overview", "probe", "grounding"})
    if query_tokens & {"flow", "sequence", "round", "handler", "loop", "runner"}:
        priority += len(path_tokens & {"round", "handler", "loop", "runner", "flow"})
    return priority


def _bucket_query_relevance(markers: tuple[str, ...], query_tokens: set[str]) -> int:
    if not query_tokens:
        return 0
    return len(set(markers) & query_tokens)


def _bucket_strength(path: str, markers: tuple[str, ...]) -> int:
    stem = Path(path).stem.lower()
    tokens = _stem_tokens(stem)
    if stem in markers:
        return 4
    if any(token in markers for token in tokens):
        return 3
    if any(marker in stem for marker in markers):
        return 2
    return 0


def _stem_tokens(stem: str) -> set[str]:
    tokens: set[str] = set()
    for separator in ("_", "-"):
        if separator in stem:
            tokens.update(part for part in stem.split(separator) if part)
    tokens.add(stem)
    return tokens


def _helper_penalty(path: str) -> int:
    stem = Path(path).stem.lower()
    return int(any(token in stem for token in ("helper", "helpers", "util", "utils")))

"""Lightweight representative source-file ranking helpers."""

from __future__ import annotations

from pathlib import Path

from allCode.memory.schema import RepoMapEntry
from allCode.tools.builtin.source_query_relevance import (
    entry_relevance_tokens,
    query_relevance_matches,
    query_relevance_score,
    query_relevance_tokens,
)
from allCode.tools.builtin.source_ranking_roles import (
    architecture_diversity_candidates,
    architecture_filename_score,
    query_relevant_candidates,
)
from allCode.workspace.source_intelligence.graph import build_source_graph, rank_exploration_candidates

ENTRYPOINT_NAMES = {"main.py", "__main__.py", "cli.py", "app.py", "index.ts", "index.js"}
TEST_MARKERS = ("test", "spec")


def representative_reads_with_metadata(
    entries: list[RepoMapEntry],
    *,
    groups: list[dict[str, object]],
    focus: str,
    limit: int = 8,
    query: str = "",
) -> tuple[list[str], list[dict[str, object]], dict[str, float]]:
    """Select representative files and explain the structural signals used.

    This intentionally stays below full graph ranking. It combines repo-map
    signatures, imports, approximate fan-in, entrypoint hints, and package
    diversity to choose a bounded set of files worth reading next.
    """

    if not entries:
        return [], [], {}
    query_tokens = _specific_query_tokens(entries, query_relevance_tokens(query))
    scores = _representative_scores(entries, focus=focus, query_tokens=query_tokens)
    selected: list[str] = []
    for group in groups:
        best = _best_for_group(entries, scores=scores, group_path=str(group.get("path") or ""))
        if best:
            _append_unique(selected, best.path)
        if len(selected) >= limit:
            break
    for entry in architecture_diversity_candidates(
        entries,
        scores=scores,
        selected=selected,
        query_tokens=query_tokens,
    ):
        _append_unique(selected, entry.path)
        if len(selected) >= limit:
            break
    for entry in query_relevant_candidates(entries, scores=scores, selected=selected, query_tokens=query_tokens):
        _append_unique(selected, entry.path)
        if len(selected) >= limit:
            break
    for entry in sorted(entries, key=lambda item: (scores.get(item.path, 0.0), -len(item.path)), reverse=True):
        _append_unique(selected, entry.path)
        if len(selected) >= limit:
            break
    selected = selected[:limit]
    reasons = [
        {
            "path": path,
            "reasons": _representative_reasons(
                _entry_by_path(entries, path),
                scores=scores,
                query_tokens=query_tokens,
            ),
        }
        for path in selected
    ]
    score_map = {path: round(float(scores.get(path, 0.0)), 4) for path in selected}
    return selected, reasons, score_map


def _representative_scores(entries: list[RepoMapEntry], *, focus: str, query_tokens: set[str]) -> dict[str, float]:
    fan_in = _fan_in_counts(entries)
    unique_groups = _group_file_counts(entries)
    graph_candidates = {
        candidate.path: candidate
        for candidate in rank_exploration_candidates(build_source_graph(entries), limit=max(12, len(entries)))
    }
    scores: dict[str, float] = {}
    for entry in entries:
        public_defs = _public_definition_count(entry)
        import_count = len([item for item in entry.imports if item])
        exported_symbols = _exported_symbol_count(entry)
        semantic_refs = _semantic_reference_count(entry)
        score = 0.0
        score += public_defs * 2.0
        score += exported_symbols * 1.2
        score += min(semantic_refs, 12) * 1.1
        score += min(import_count, 8) * 0.8
        score += min(fan_in.get(entry.path, 0), 8) * 1.4
        if Path(entry.path).name in ENTRYPOINT_NAMES:
            score += 2.5
        score += architecture_filename_score(entry.path)
        if unique_groups.get(_group_key(entry.path), 0) == 1 and public_defs:
            score += 0.8
        if focus == "tests" and _looks_test_path(entry.path):
            score += 4.0
        if _is_private_or_generated(entry.path):
            score -= 2.0
        graph_candidate = graph_candidates.get(entry.path)
        if graph_candidate is not None:
            score += max(0.0, graph_candidate.score) * 0.35
        score += query_relevance_score(entry, query_tokens)
        scores[entry.path] = score
    return scores


def _specific_query_tokens(entries: list[RepoMapEntry], query_tokens: set[str]) -> set[str]:
    if not query_tokens or len(entries) < 2:
        return query_tokens
    token_counts: dict[str, int] = {}
    for entry in entries:
        for token in entry_relevance_tokens(entry) & query_tokens:
            token_counts[token] = token_counts.get(token, 0) + 1
    common_threshold = max(2, int(len(entries) * 0.6))
    common_tokens = {token for token, count in token_counts.items() if count >= common_threshold}
    return query_tokens - common_tokens


def _best_for_group(
    entries: list[RepoMapEntry],
    *,
    scores: dict[str, float],
    group_path: str,
) -> RepoMapEntry | None:
    candidates = [
        entry
        for entry in entries
        if entry.path == group_path or (group_path and entry.path.startswith(f"{group_path}/"))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (scores.get(item.path, 0.0), len(item.definitions), -len(item.path)))


def _fan_in_counts(entries: list[RepoMapEntry]) -> dict[str, int]:
    module_names = {entry.path: _module_aliases(entry.path) for entry in entries}
    counts = {entry.path: 0 for entry in entries}
    for source in entries:
        imports = " ".join(source.imports).replace("/", ".").lower()
        if not imports:
            continue
        for path, aliases in module_names.items():
            if path == source.path:
                continue
            if any(alias and alias in imports for alias in aliases):
                counts[path] += 1
    return counts


def _module_aliases(path: str) -> set[str]:
    stem = Path(path).stem.lower()
    no_suffix = str(Path(path).with_suffix("")).replace("/", ".").lower()
    parts = [part for part in no_suffix.split(".") if part]
    aliases = {stem, no_suffix}
    if parts:
        aliases.add(".".join(parts[-2:]))
        aliases.add(parts[-1])
    return {alias for alias in aliases if alias}


def _public_definition_count(entry: RepoMapEntry) -> int:
    count = 0
    for definition in entry.definitions:
        name = _definition_name(definition)
        if name and not name.startswith("_"):
            count += 1
    return count


def _definition_name(definition: str) -> str:
    cleaned = definition.strip()
    for marker in ("class ", "def ", "async def ", "function ", "const ", "let ", "var "):
        if marker in cleaned:
            tail = cleaned.split(marker, 1)[1].strip()
            return tail.split("(", 1)[0].split(":", 1)[0].split("=", 1)[0].strip()
    return cleaned.split("(", 1)[0].strip()


def _group_file_counts(entries: list[RepoMapEntry]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        key = _group_key(entry.path)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _group_key(path: str) -> str:
    parent = Path(path).parent.as_posix()
    return parent or "."


def _representative_reasons(
    entry: RepoMapEntry | None,
    *,
    scores: dict[str, float],
    query_tokens: set[str],
) -> list[str]:
    if entry is None:
        return []
    reasons: list[str] = []
    if _public_definition_count(entry):
        reasons.append("public definitions")
    if _exported_symbol_count(entry):
        reasons.append("exported symbols")
    if _semantic_reference_count(entry):
        reasons.append("semantic references")
    if _graph_edge_count(entry):
        reasons.append("source graph edges")
    if entry.imports:
        reasons.append("import fan-out")
    if Path(entry.path).name in ENTRYPOINT_NAMES:
        reasons.append("entrypoint candidate")
    if scores.get(entry.path, 0.0) > 0:
        reasons.append("highest ranked candidate in package")
    if _looks_test_path(entry.path):
        reasons.append("test/spec file")
    if query_relevance_matches(entry, query_tokens):
        reasons.append("query relevance")
    return reasons or ["source file candidate"]


def _entry_by_path(entries: list[RepoMapEntry], path: str) -> RepoMapEntry | None:
    for entry in entries:
        if entry.path == path:
            return entry
    return None


def _exported_symbol_count(entry: RepoMapEntry) -> int:
    count = 0
    for item in entry.symbols:
        if not isinstance(item, dict):
            continue
        if item.get("exported") is True and str(item.get("visibility") or "public") == "public":
            count += 1
    return count


def _semantic_reference_count(entry: RepoMapEntry) -> int:
    count = 0
    for item in entry.references_detail:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if kind in {"call", "reference", "inheritance", "import"}:
            count += 1
    return count


def _graph_edge_count(entry: RepoMapEntry) -> int:
    count = 0
    for item in entry.references_detail:
        if isinstance(item, dict) and str(item.get("kind") or "") in {"call", "inheritance", "reference"}:
            count += 1
    count += len([item for item in entry.imports if item])
    return count


def _looks_test_path(path: str) -> bool:
    lowered = path.lower()
    return any(marker in lowered for marker in TEST_MARKERS)


def _is_private_or_generated(path: str) -> bool:
    lowered = Path(path).name.lower()
    return lowered.endswith((".min.js", ".generated.py", ".pb.go")) or lowered.startswith("_")


def _append_unique(paths: list[str], path: str) -> None:
    if path and path not in paths:
        paths.append(path)

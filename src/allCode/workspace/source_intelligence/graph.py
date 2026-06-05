"""Lightweight source graph helpers for bounded repo exploration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.memory.schema import RepoMapEntry

EdgeKind = Literal["import", "call_hint", "inheritance", "reference"]


class SourceGraphNode(CoreModel):
    path: str
    language: str = ""
    public_symbol_count: int = 0
    symbol_names: list[str] = Field(default_factory=list)
    import_count: int = 0
    entrypoint_score: float = 0.0


class SourceGraphEdge(CoreModel):
    source_path: str
    target_path: str
    kind: EdgeKind
    symbol: str = ""
    confidence: float = 0.5


class SourceExplorationCandidate(CoreModel):
    path: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    incoming_edges: int = 0
    outgoing_edges: int = 0


class SourceGraph(CoreModel):
    nodes: dict[str, SourceGraphNode] = Field(default_factory=dict)
    edges: list[SourceGraphEdge] = Field(default_factory=list)

    def incoming_counts(self) -> dict[str, int]:
        counts = {path: 0 for path in self.nodes}
        for edge in self.edges:
            counts[edge.target_path] = counts.get(edge.target_path, 0) + 1
        return counts

    def outgoing_counts(self) -> dict[str, int]:
        counts = {path: 0 for path in self.nodes}
        for edge in self.edges:
            counts[edge.source_path] = counts.get(edge.source_path, 0) + 1
        return counts


ENTRYPOINT_NAMES = {"__main__.py", "main.py", "cli.py", "app.py", "runtime.py", "index.ts", "index.js"}


def build_source_graph(entries: list[RepoMapEntry]) -> SourceGraph:
    nodes = {_clean_path(entry.path): _node_for_entry(entry) for entry in entries}
    edges: list[SourceGraphEdge] = []
    module_index = _module_index(entries)
    symbol_index = _symbol_index(entries)
    for entry in entries:
        source_path = _clean_path(entry.path)
        edges.extend(_import_edges(entry, source_path=source_path, module_index=module_index))
        edges.extend(_reference_edges(entry, source_path=source_path, symbol_index=symbol_index))
    return SourceGraph(nodes=nodes, edges=_dedupe_edges(edges))


def rank_exploration_candidates(
    graph: SourceGraph,
    *,
    prompt_terms: set[str] | None = None,
    observed_paths: set[str] | None = None,
    limit: int = 12,
) -> list[SourceExplorationCandidate]:
    prompt_terms = {term.lower() for term in prompt_terms or set() if term}
    observed_paths = {_clean_path(path) for path in observed_paths or set()}
    incoming = graph.incoming_counts()
    outgoing = graph.outgoing_counts()
    candidates: list[SourceExplorationCandidate] = []
    for path, node in graph.nodes.items():
        reasons: list[str] = []
        score = 0.0
        if path in observed_paths:
            score -= 20.0
            reasons.append("already observed")
        if node.public_symbol_count:
            score += min(node.public_symbol_count, 8) * 2.0
            reasons.append("public symbols")
        if incoming.get(path, 0):
            score += min(incoming[path], 10) * 1.7
            reasons.append("incoming references")
        if outgoing.get(path, 0):
            score += min(outgoing[path], 10) * 1.0
            reasons.append("outgoing dependencies")
        if node.entrypoint_score:
            score += node.entrypoint_score
            reasons.append("entrypoint candidate")
        if _matches_prompt(path, node.symbol_names, prompt_terms):
            score += 8.0
            reasons.append("matches prompt target")
        if _looks_test_path(path):
            score += 1.5
            reasons.append("test/spec evidence")
        if _looks_generated_or_private(path):
            score -= 3.0
            reasons.append("private or generated penalty")
        candidates.append(
            SourceExplorationCandidate(
                path=path,
                score=round(score, 4),
                reasons=reasons or ["source graph candidate"],
                symbols=node.symbol_names[:8],
                incoming_edges=incoming.get(path, 0),
                outgoing_edges=outgoing.get(path, 0),
            )
        )
    return sorted(candidates, key=lambda item: (item.score, -len(item.path)), reverse=True)[:limit]


def prompt_terms(prompt: str) -> set[str]:
    terms = set()
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", prompt):
        terms.add(token)
    for token in re.findall(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+", prompt):
        terms.update(part for part in Path(token).parts if part)
    return terms


def _node_for_entry(entry: RepoMapEntry) -> SourceGraphNode:
    path = _clean_path(entry.path)
    symbols = _entry_symbol_names(entry)
    return SourceGraphNode(
        path=path,
        language=entry.language or "",
        public_symbol_count=len([symbol for symbol in symbols if not symbol.startswith("_")]),
        symbol_names=symbols,
        import_count=len([item for item in entry.imports if item]),
        entrypoint_score=2.5 if Path(path).name in ENTRYPOINT_NAMES else 0.0,
    )


def _module_index(entries: list[RepoMapEntry]) -> dict[str, str]:
    index: dict[str, str] = {}
    for entry in entries:
        path = _clean_path(entry.path)
        for alias in _module_aliases(path):
            index.setdefault(alias, path)
    return index


def _symbol_index(entries: list[RepoMapEntry]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for entry in entries:
        path = _clean_path(entry.path)
        for name in _entry_symbol_names(entry):
            for alias in {name.lower(), name.rsplit(".", 1)[-1].lower()}:
                if alias:
                    index.setdefault(alias, []).append(path)
    return index


def _import_edges(entry: RepoMapEntry, *, source_path: str, module_index: dict[str, str]) -> list[SourceGraphEdge]:
    edges: list[SourceGraphEdge] = []
    modules = [str(item.get("module") or "") for item in entry.imports_detail if isinstance(item, dict)]
    modules.extend(entry.imports)
    for module in modules:
        target = _resolve_module(module, source_path=source_path, module_index=module_index)
        if target and target != source_path:
            edges.append(SourceGraphEdge(source_path=source_path, target_path=target, kind="import", symbol=module, confidence=0.85))
    return edges


def _reference_edges(entry: RepoMapEntry, *, source_path: str, symbol_index: dict[str, list[str]]) -> list[SourceGraphEdge]:
    edges: list[SourceGraphEdge] = []
    for item in entry.references_detail:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "reference")
        if kind not in {"call", "inheritance", "reference"}:
            continue
        symbol = str(item.get("symbol") or item.get("target_hint") or "").rsplit(".", 1)[-1].lower()
        for target in symbol_index.get(symbol, [])[:4]:
            if target != source_path:
                edges.append(
                    SourceGraphEdge(source_path=source_path, target_path=target, kind=_edge_kind(kind), symbol=symbol, confidence=float(item.get("confidence") or 0.5))
                )
    return edges


def _resolve_module(module: str, *, source_path: str, module_index: dict[str, str]) -> str:
    cleaned = module.strip().strip(".")
    if not cleaned:
        return ""
    aliases = {cleaned.lower(), cleaned.replace("/", ".").lower(), cleaned.rsplit(".", 1)[-1].lower()}
    parent_parts = Path(source_path).parent.parts
    if module.startswith(".") and parent_parts:
        aliases.add(".".join([*parent_parts, cleaned]).lower())
        aliases.add(".".join([parent_parts[-1], cleaned]).lower())
    for alias in aliases:
        if alias in module_index:
            return module_index[alias]
    return ""


def _entry_symbol_names(entry: RepoMapEntry) -> list[str]:
    names: list[str] = []
    for item in entry.symbols:
        if isinstance(item, dict):
            _append_unique(names, str(item.get("scope") or item.get("name") or ""))
    if names:
        return names[:40]
    for definition in entry.definitions:
        _append_unique(names, _definition_name(definition))
    return names[:40]


def _definition_name(definition: str) -> str:
    cleaned = definition.strip()
    for marker in ("async def ", "def ", "class ", "function ", "const ", "let ", "var "):
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[1]
            break
    return cleaned.split("(", 1)[0].split(":", 1)[0].split("=", 1)[0].strip()


def _module_aliases(path: str) -> set[str]:
    stem = Path(path).stem.lower()
    without_suffix = Path(path).with_suffix("").as_posix().replace("/", ".").lower()
    parts = [part for part in without_suffix.split(".") if part]
    aliases = {stem, without_suffix}
    if parts:
        aliases.add(parts[-1])
        aliases.add(".".join(parts[-2:]))
        aliases.add(".".join(parts[-3:]))
    return {alias for alias in aliases if alias}


def _dedupe_edges(edges: list[SourceGraphEdge]) -> list[SourceGraphEdge]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[SourceGraphEdge] = []
    for edge in edges:
        key = (edge.source_path, edge.target_path, edge.kind, edge.symbol)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)
    return deduped[:2_000]


def _matches_prompt(path: str, symbols: list[str], terms: set[str]) -> bool:
    if not terms:
        return False
    haystack = " ".join([path, *symbols]).lower()
    return any(term and term in haystack for term in terms)


def _edge_kind(kind: str) -> EdgeKind:
    if kind == "call":
        return "call_hint"
    if kind == "inheritance":
        return "inheritance"
    return "reference"


def _looks_test_path(path: str) -> bool:
    lowered = path.lower()
    return "/test" in lowered or "tests/" in lowered or lowered.endswith(("_test.py", ".spec.ts"))


def _looks_generated_or_private(path: str) -> bool:
    name = Path(path).name.lower()
    return name.startswith("_") or name.endswith((".min.js", ".generated.py", ".pb.go"))


def _clean_path(path: str) -> str:
    return str(path or "").strip().strip("`").replace("\\", "/")


def _append_unique(values: list[str], value: str) -> None:
    cleaned = value.strip()
    if cleaned and cleaned not in values:
        values.append(cleaned)

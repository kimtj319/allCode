"""Aider-style compact repo map generation."""

from __future__ import annotations

import json
from pathlib import Path

from allCode.memory.repo_ranker import RepoRanker
from allCode.memory.schema import RecentTarget, RepoMapEntry
from allCode.workspace.indexer import WorkspaceIndex
from allCode.workspace.symbol_index import SymbolIndexer


class RepoMapBuilder:
    def __init__(self, *, symbol_indexer: SymbolIndexer | None = None, ranker: RepoRanker | None = None, cache_path: Path | None = None) -> None:
        self.symbol_indexer = symbol_indexer or SymbolIndexer()
        self.ranker = ranker or RepoRanker()
        self.cache_path = cache_path

    def build_entries(self, index: WorkspaceIndex) -> list[RepoMapEntry]:
        entries: list[RepoMapEntry] = []
        for record in index.source_files():
            symbols = self.symbol_indexer.extract(record.path)
            definitions = [symbol.signature for symbol in symbols.definitions]
            summary = self._summary(record.relative_path, definitions, symbols.imports)
            entries.append(
                RepoMapEntry(
                    path=record.relative_path,
                    language=record.language,
                    definitions=definitions,
                    references=symbols.references,
                    imports=symbols.imports,
                    summary=summary,
                    mtime=record.mtime,
                )
            )
        if self.cache_path is not None:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps([entry.model_dump(mode="json") for entry in entries], ensure_ascii=False, indent=2), encoding="utf-8")
        return entries

    def load_cache(self) -> list[RepoMapEntry]:
        if self.cache_path is None or not self.cache_path.exists():
            return []
        return [RepoMapEntry.model_validate(item) for item in json.loads(self.cache_path.read_text(encoding="utf-8"))]

    def compact_text(
        self,
        entries: list[RepoMapEntry],
        *,
        prompt: str,
        recent_targets: list[RecentTarget] | None = None,
        token_budget: int = 1200,
    ) -> str:
        ranked = self.ranker.rank(entries, prompt=prompt, recent_targets=recent_targets)
        lines: list[str] = []
        used = 0
        for entry in ranked:
            block = self._entry_text(entry)
            estimated = max(1, len(block) // 4)
            if used + estimated > token_budget and lines:
                break
            lines.append(block)
            used += estimated
        return "\n".join(lines)

    def _entry_text(self, entry: RepoMapEntry) -> str:
        if entry.definitions:
            parts = [f"{entry.path}: {'; '.join(entry.definitions[:12])}"]
        else:
            parts = [f"{entry.path} [{entry.language or 'text'}]"]
        if entry.imports:
            parts.append("imports: " + ", ".join(entry.imports[:8]))
        return "\n".join(parts)

    def _summary(self, relative_path: str, definitions: list[str], imports: list[str]) -> str:
        fragments = [relative_path]
        if definitions:
            fragments.append("definitions: " + ", ".join(definitions[:5]))
        if imports:
            fragments.append("imports: " + ", ".join(imports[:5]))
        return " | ".join(fragments)

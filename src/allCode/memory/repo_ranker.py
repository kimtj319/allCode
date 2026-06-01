"""Simple weighted repo-map ranking."""

from __future__ import annotations

from pathlib import Path

from allCode.memory.schema import RecentTarget, RepoMapEntry


class RepoRanker:
    def rank(
        self,
        entries: list[RepoMapEntry],
        *,
        prompt: str,
        recent_targets: list[RecentTarget] | None = None,
        mode: str = "inspect",
    ) -> list[RepoMapEntry]:
        lowered = prompt.lower()
        recent_targets = recent_targets or []
        ranked: list[RepoMapEntry] = []
        for entry in entries:
            score = 0.0
            path = Path(entry.path)
            if entry.path.lower() in lowered or path.name.lower() in lowered:
                score += 10
            for target in recent_targets:
                target_path = Path(target.path)
                if target.path == entry.path:
                    score += 8
                elif target_path.parent == path.parent:
                    score += 4
            for definition in entry.definitions:
                if definition.lower() in lowered:
                    score += 5
            if "test" in path.name.lower():
                score += 2 if mode == "modify" else 1
            ranked.append(entry.model_copy(update={"score": score}))
        return sorted(ranked, key=lambda item: (-item.score, item.path))

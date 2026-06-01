"""Hierarchical memory merge logic."""

from __future__ import annotations

import hashlib

from allCode.memory.schema import MemoryItem, RecentTarget


class MemoryHierarchy:
    SCOPE_WEIGHT = {"global": 1, "project": 2, "directory": 3, "session": 4}

    def merge(
        self,
        items: list[MemoryItem],
        *,
        session_summary: str | None = None,
        recent_targets: list[RecentTarget] | None = None,
    ) -> list[MemoryItem]:
        merged = list(items)
        if session_summary:
            merged.append(MemoryItem(scope="session", kind="workflow", text=session_summary, evidence=["session_summary"]))
        for target in recent_targets or []:
            merged.append(
                MemoryItem(
                    scope="session",
                    kind="recent_target",
                    text=f"{target.target_type}: {target.path} {target.symbol or ''} {target.summary}".strip(),
                    evidence=[target.path],
                )
            )
        return self._dedupe(merged)

    def _dedupe(self, items: list[MemoryItem]) -> list[MemoryItem]:
        best: dict[str, MemoryItem] = {}
        for item in items:
            key = hashlib.sha256(f"{item.kind}:{item.text}".encode("utf-8")).hexdigest()
            existing = best.get(key)
            if existing is None or self.SCOPE_WEIGHT[item.scope] >= self.SCOPE_WEIGHT[existing.scope]:
                best[key] = item
        return sorted(best.values(), key=lambda item: (item.kind != "constraint", -self.SCOPE_WEIGHT[item.scope], item.created_at.isoformat()))

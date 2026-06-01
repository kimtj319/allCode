"""Approval inbox for auto-memory candidates."""

from __future__ import annotations

from pathlib import Path

from allCode.memory.schema import MemoryItem
from allCode.memory.store import MemoryStore


class MemoryInbox:
    def __init__(self, inbox_dir: Path, store: MemoryStore) -> None:
        self.inbox_dir = inbox_dir.expanduser().resolve()
        self.store = store

    async def add_candidate(self, item: MemoryItem) -> None:
        candidate = item.model_copy(update={"approved": False})
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self._path(candidate.id).write_text(candidate.model_dump_json(), encoding="utf-8")

    async def list_candidates(self) -> list[MemoryItem]:
        if not self.inbox_dir.exists():
            return []
        return [MemoryItem.model_validate_json(path.read_text(encoding="utf-8")) for path in sorted(self.inbox_dir.glob("*.json"))]

    async def approve(self, candidate_id: str) -> MemoryItem:
        path = self._path(candidate_id)
        item = MemoryItem.model_validate_json(path.read_text(encoding="utf-8"))
        approved = item.model_copy(update={"approved": True})
        await self.store.add_item(approved)
        path.unlink()
        return approved

    async def reject(self, candidate_id: str) -> None:
        path = self._path(candidate_id)
        if path.exists():
            tombstone = self.inbox_dir / f"{candidate_id}.rejected"
            tombstone.write_text("rejected\n", encoding="utf-8")
            path.unlink()

    def _path(self, candidate_id: str) -> Path:
        return self.inbox_dir / f"{candidate_id}.json"

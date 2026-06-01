"""Durable memory store for ALLCODE.md and structured memory items."""

from __future__ import annotations

import json
from pathlib import Path

from allCode.memory.redaction import redact_text
from allCode.memory.schema import MemoryItem, MemoryKind


class MemoryStore:
    def __init__(self, project_root: Path, global_config_dir: Path) -> None:
        self.project_root = project_root.expanduser().resolve()
        self.global_config_dir = global_config_dir.expanduser().resolve()
        self.project_memory_path = self.project_root / ".allCode" / "ALLCODE.md"
        self.items_path = self.project_root / ".allCode" / "memory" / "items.jsonl"
        self.global_memory_path = self.global_config_dir / "ALLCODE.md"

    async def load_active_items(self, *, cwd: Path) -> list[MemoryItem]:
        items: list[MemoryItem] = []
        items.extend(self._read_markdown(self.global_memory_path, scope="global"))
        items.extend(self._read_markdown(self.project_memory_path, scope="project"))
        items.extend(self._read_directory_memories(cwd))
        items.extend(self._read_structured_items())
        return [item for item in items if item.approved]

    async def add_item(self, item: MemoryItem) -> None:
        self.items_path.parent.mkdir(parents=True, exist_ok=True)
        clean = item.model_copy(update={"text": redact_text(item.text)})
        with self.items_path.open("a", encoding="utf-8") as handle:
            handle.write(clean.model_dump_json() + "\n")

    async def update_item(self, item: MemoryItem) -> None:
        items = [existing for existing in self._read_structured_items() if existing.id != item.id]
        items.append(item.model_copy(update={"text": redact_text(item.text)}))
        self._write_items(items)

    async def delete_item(self, item_id: str) -> None:
        self._write_items([item for item in self._read_structured_items() if item.id != item_id])

    def _write_items(self, items: list[MemoryItem]) -> None:
        self.items_path.parent.mkdir(parents=True, exist_ok=True)
        with self.items_path.open("w", encoding="utf-8") as handle:
            for item in items:
                clean = item.model_copy(update={"text": redact_text(item.text)})
                handle.write(clean.model_dump_json() + "\n")

    def _read_structured_items(self) -> list[MemoryItem]:
        if not self.items_path.exists():
            return []
        items = []
        for line in self.items_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(MemoryItem.model_validate_json(line))
        return items

    def _read_directory_memories(self, cwd: Path) -> list[MemoryItem]:
        resolved = cwd.expanduser().resolve()
        paths: list[Path] = []
        try:
            relative = resolved.relative_to(self.project_root)
        except ValueError:
            relative = Path()
        current = self.project_root
        for part in relative.parts:
            current = current / part
            paths.append(current / ".allCode" / "ALLCODE.md")
        items: list[MemoryItem] = []
        for path in paths:
            items.extend(self._read_markdown(path, scope="directory"))
        return items

    def _read_markdown(self, path: Path, *, scope) -> list[MemoryItem]:
        if not path.exists():
            return []
        items: list[MemoryItem] = []
        current_kind: MemoryKind = "instruction"
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                current_kind = self._kind_from_heading(line)
                continue
            text = line[2:].strip() if line.startswith(("- ", "* ")) else line
            items.append(MemoryItem(scope=scope, kind=current_kind, text=text, evidence=[str(path)]))
        return items

    def _kind_from_heading(self, heading: str) -> MemoryKind:
        lowered = heading.lower()
        if "constraint" in lowered or "금지" in lowered:
            return "constraint"
        if "preference" in lowered or "선호" in lowered:
            return "preference"
        if "workflow" in lowered:
            return "workflow"
        if "verification" in lowered or "test" in lowered:
            return "verification_command"
        return "instruction"

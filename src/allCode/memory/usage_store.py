"""Per-day token usage tally for the /status gauge.

Records how many model tokens (prompt + completion) were consumed each calendar
day, persisted to ``.allCode/usage.json`` so the /status meter reflects the
whole day across allCode launches. Kept tiny (a date→tokens map, pruned to the
recent past)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

_KEEP_DAYS = 30


class UsageStore:
    def __init__(self, project_root: str | Path, *, today: str | None = None) -> None:
        self.path = Path(project_root).expanduser() / ".allCode" / "usage.json"
        self._today = today or date.today().isoformat()

    def add(self, tokens: int) -> None:
        if not tokens or tokens <= 0:
            return
        data = self._load()
        data[self._today] = int(data.get(self._today, 0)) + int(tokens)
        self._prune(data)
        self._save(data)

    def today_total(self) -> int:
        return int(self._load().get(self._today, 0))

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            return {str(k): int(v) for k, v in loaded.items()} if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            return {}

    def _prune(self, data: dict) -> None:
        if len(data) <= _KEEP_DAYS:
            return
        for old in sorted(data.keys())[: len(data) - _KEEP_DAYS]:
            data.pop(old, None)

    def _save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            return

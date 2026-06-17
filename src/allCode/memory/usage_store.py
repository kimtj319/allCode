"""Per-day token usage tally for the /status gauge.

Records how many model tokens (prompt + completion) were consumed each calendar
day, persisted to ``.allCode/usage.json`` so the /status meter reflects the
whole day across allCode launches. Usage is also broken down per model name so
the gauge can show, e.g., the ultra model vs the implementation/max model
separately. Kept tiny (a date→{model→tokens} map, pruned to the recent past)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

_KEEP_DAYS = 30
# Reserved key inside each day's bucket holding the day's grand total across all
# models (including calls that did not report a model name).
_TOTAL_KEY = "_total"


class UsageStore:
    def __init__(self, project_root: str | Path, *, today: str | None = None) -> None:
        self.path = Path(project_root).expanduser() / ".allCode" / "usage.json"
        self._today = today or date.today().isoformat()

    def add(self, tokens: int, model: str | None = None) -> None:
        if not tokens or tokens <= 0:
            return
        data = self._load()
        bucket = data.setdefault(self._today, {})
        bucket[_TOTAL_KEY] = int(bucket.get(_TOTAL_KEY, 0)) + int(tokens)
        name = (model or "").strip()
        if name:
            bucket[name] = int(bucket.get(name, 0)) + int(tokens)
        self._prune(data)
        self._save(data)

    def today_total(self) -> int:
        return int(self._load().get(self._today, {}).get(_TOTAL_KEY, 0))

    def today_by_model(self) -> dict[str, int]:
        """Per-model token totals for today (excludes the grand-total key).

        Returned in descending usage order so callers can render the busiest
        model first."""
        bucket = self._load().get(self._today, {})
        models = {k: int(v) for k, v in bucket.items() if k != _TOTAL_KEY}
        return dict(sorted(models.items(), key=lambda item: item[1], reverse=True))

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(loaded, dict):
            return {}
        normalized: dict[str, dict[str, int]] = {}
        for day, value in loaded.items():
            normalized[str(day)] = self._normalize_bucket(value)
        return normalized

    @staticmethod
    def _normalize_bucket(value) -> dict[str, int]:
        # Backward compatibility: the older format stored a bare integer total
        # per day. Promote it to the {_total: N} bucket shape.
        if isinstance(value, (int, float)):
            return {_TOTAL_KEY: int(value)}
        if isinstance(value, dict):
            bucket: dict[str, int] = {}
            for key, count in value.items():
                try:
                    bucket[str(key)] = int(count)
                except (TypeError, ValueError):
                    continue
            return bucket
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

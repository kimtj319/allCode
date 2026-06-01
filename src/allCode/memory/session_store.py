"""Append-only session transcript persistence."""

from __future__ import annotations

import json
from pathlib import Path

from allCode.core.models import TurnState
from allCode.memory.redaction import redact_data


class SessionStore:
    def __init__(self, project_root: Path) -> None:
        self.sessions_dir = project_root.expanduser().resolve() / ".allCode" / "sessions"

    async def append_turn(self, session_id: str, turn: TurnState) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        payload = redact_data(turn.model_dump(mode="json"))
        with self._path(session_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    async def load_turns(self, session_id: str, *, limit: int | None = None) -> list[TurnState]:
        path = self._path(session_id)
        if not path.exists():
            return []
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if limit is not None:
            lines = lines[-limit:]
        return [TurnState.model_validate(json.loads(line)) for line in lines]

    async def list_sessions(self) -> list[str]:
        if not self.sessions_dir.exists():
            return []
        return sorted(path.stem for path in self.sessions_dir.glob("*.jsonl"))

    async def clear_session(self, session_id: str) -> None:
        path = self._path(session_id)
        if path.exists():
            path.unlink()

    def _path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.jsonl"

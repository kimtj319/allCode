"""Session summary generation and persistence."""

from __future__ import annotations

from pathlib import Path

from allCode.core.models import TurnState
from allCode.memory.redaction import redact_text


class SessionSummary:
    def __init__(self, project_root: Path) -> None:
        self.sessions_dir = project_root.expanduser().resolve() / ".allCode" / "sessions"

    def summarize(self, turns: list[TurnState]) -> str:
        goals: list[str] = []
        touched: list[str] = []
        for turn in turns:
            for message in turn.messages:
                if message.role == "user" and message.content:
                    goals.append(message.content.strip())
            touched.extend(turn.created_files)
            touched.extend(turn.modified_files)
        sections = []
        if goals:
            sections.append("Goals:\n" + "\n".join(f"- {redact_text(goal)}" for goal in goals[-5:]))
        if touched:
            unique = []
            for path in touched:
                if path not in unique:
                    unique.append(path)
            sections.append("Touched files:\n" + "\n".join(f"- {path}" for path in unique[-20:]))
        return "\n\n".join(sections)

    async def save(self, session_id: str, summary: str) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._path(session_id).write_text(redact_text(summary), encoding="utf-8")

    async def load(self, session_id: str) -> str:
        path = self._path(session_id)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.summary.md"

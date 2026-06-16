"""Compact per-session conversation persistence for resume/continue.

Stores the user prompt and assistant answer of each turn so a later launch can
reload the back-and-forth and continue the conversation. This is deliberately
small (just the visible exchange), separate from the richer state snapshot and
telemetry logs.
"""

from __future__ import annotations

import json
from pathlib import Path


class ConversationStore:
    def __init__(self, project_root: Path | str) -> None:
        self.dir = Path(project_root).expanduser().resolve() / ".allCode" / "sessions" / "conversation"

    def _path(self, session_id: str) -> Path:
        return self.dir / f"{session_id}.jsonl"

    def append_exchange(self, session_id: str, *, prompt: str, answer: str) -> None:
        if not session_id:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        if prompt and prompt.strip():
            lines.append(json.dumps({"role": "user", "text": prompt}, ensure_ascii=False))
        if answer and answer.strip():
            lines.append(json.dumps({"role": "assistant", "text": answer}, ensure_ascii=False))
        if not lines:
            return
        with self._path(session_id).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    def load(self, session_id: str) -> list[tuple[str, str]]:
        path = self._path(session_id)
        if not path.exists():
            return []
        exchanges: list[tuple[str, str]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            role = str(record.get("role", ""))
            text = str(record.get("text", ""))
            if role and text:
                exchanges.append((role, text))
        return exchanges

    def latest_session_id(self) -> str | None:
        if not self.dir.exists():
            return None
        files = [p for p in self.dir.glob("*.jsonl") if p.is_file()]
        if not files:
            return None
        newest = max(files, key=lambda p: p.stat().st_mtime)
        return newest.stem

    def list_sessions(self) -> list[str]:
        if not self.dir.exists():
            return []
        files = [p for p in self.dir.glob("*.jsonl") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.stem for p in files]

    # -- naming & fork --------------------------------------------------------

    def _names_path(self) -> Path:
        return self.dir / "_names.json"

    def _load_names(self) -> dict[str, str]:
        path = self._names_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def set_name(self, session_id: str, name: str) -> None:
        """Map a human name to a session id (for /resume <name>)."""
        name = (name or "").strip()
        if not name or not session_id:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        names = self._load_names()
        names[name] = session_id
        try:
            self._names_path().write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            return

    def resolve(self, token: str) -> str | None:
        """Resolve a session reference that may be an id or a registered name."""
        token = (token or "").strip()
        if not token:
            return None
        if token in self.list_sessions():
            return token
        return self._load_names().get(token)

    def fork(self, source_id: str, new_id: str) -> bool:
        """Copy a session's conversation into a new id (branch the dialogue)."""
        source = self._path(source_id)
        if not source.exists() or not new_id:
            return False
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            self._path(new_id).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            return False
        return True

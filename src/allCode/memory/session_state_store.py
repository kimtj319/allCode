"""Compact persistent session-state snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.memory.project_obligations import (
    ActiveProjectObligations,
    LatestRepairContext,
    SourceExplorationLedger,
)
from allCode.memory.redaction import redact_data


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStateFileFreshness(CoreModel):
    path: str
    exists: bool = False
    mtime: float | None = None
    size: int | None = None


class SessionStateSnapshot(CoreModel):
    session_id: str
    active_project_obligations: ActiveProjectObligations | None = None
    latest_repair_context: LatestRepairContext | None = None
    source_exploration_ledger: SourceExplorationLedger | None = None
    file_freshness: list[SessionStateFileFreshness] = Field(default_factory=list)
    stale_paths: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=_utc_timestamp)


class SessionStateStore:
    """Read and write compact session-state snapshots under the workspace."""

    def __init__(self, project_root: Path) -> None:
        self.state_dir = project_root.expanduser().resolve() / ".allCode" / "sessions" / "state"

    async def save_snapshot(self, snapshot: SessionStateSnapshot) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = redact_data(snapshot.model_dump(mode="json"))
        with self._path(snapshot.session_id).open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")

    async def load_snapshot(self, session_id: str, *, workspace_root: str) -> SessionStateSnapshot | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            snapshot = SessionStateSnapshot.model_validate(payload)
        except (OSError, ValueError):
            return None
        stale_paths = stale_freshness_paths(snapshot.file_freshness, workspace_root=workspace_root)
        return snapshot.model_copy(update={"stale_paths": stale_paths})

    def _path(self, session_id: str) -> Path:
        return self.state_dir / f"{session_id}.json"


def build_freshness_metadata(paths: list[str], *, workspace_root: str) -> list[SessionStateFileFreshness]:
    root = Path(workspace_root).expanduser().resolve()
    rows: list[SessionStateFileFreshness] = []
    for raw_path in _dedupe(paths):
        relative = _workspace_relative(raw_path, root=root)
        if not relative:
            continue
        path = root / relative
        exists = path.exists()
        stat = path.stat() if exists else None
        rows.append(
            SessionStateFileFreshness(
                path=relative,
                exists=exists,
                mtime=stat.st_mtime if stat is not None else None,
                size=stat.st_size if stat is not None else None,
            )
        )
    return rows


def stale_freshness_paths(rows: list[SessionStateFileFreshness], *, workspace_root: str) -> list[str]:
    root = Path(workspace_root).expanduser().resolve()
    stale: list[str] = []
    for row in rows:
        path = root / row.path
        exists = path.exists()
        if exists != row.exists:
            stale.append(row.path)
            continue
        if not exists:
            continue
        stat = path.stat()
        if row.size is not None and stat.st_size != row.size:
            stale.append(row.path)
            continue
        if row.mtime is not None and abs(stat.st_mtime - row.mtime) > 1.0:
            stale.append(row.path)
    return stale


def _workspace_relative(raw_path: str, *, root: Path) -> str:
    value = str(raw_path or "").strip()
    if not value:
        return ""
    path = Path(value)
    if not path.is_absolute():
        normalized = path.as_posix().lstrip("/")
        if normalized.startswith("../") or normalized == "..":
            return ""
        return normalized
    try:
        return path.expanduser().resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return ""


def _dedupe(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen

"""Filesystem paths for append-only session logs."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from allCode.config.defaults import DEFAULT_SESSION_LOG_ROOT

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_name(value: str, *, fallback: str = "session") -> str:
    cleaned = _SAFE_NAME.sub("_", value.strip()).strip("._-")
    return cleaned[:80] or fallback


def make_session_name(*, workspace_label: str, now: datetime | None = None, suffix: str | None = None) -> str:
    current = now or utc_now()
    timestamp = current.strftime("%Y%m%d_%H%M%S")
    workspace = safe_name(workspace_label, fallback="workspace")
    tail = suffix or uuid4().hex[:8]
    return f"{timestamp}-{workspace}-{tail}"


def session_log_path(
    session_name: str,
    *,
    base_dir: Path | None = None,
    now: datetime | None = None,
) -> Path:
    current = now or utc_now()
    root = (base_dir or DEFAULT_SESSION_LOG_ROOT).expanduser()
    return root / current.strftime("%Y") / current.strftime("%m") / current.strftime("%d") / f"{safe_name(session_name)}.jsonl"

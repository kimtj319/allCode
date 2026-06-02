"""Strict JSONL schema for session telemetry records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import Field, field_validator

from allCode.core.models import CoreModel, _json_safe


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentLogRecord(CoreModel):
    schema_version: int = 1
    timestamp: datetime = Field(default_factory=_utc_now)
    sequence: int
    session_id: str
    session_name: str
    turn_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    record_kind: str = "event"
    category: str
    event_type: str
    severity: str = "debug_only"
    message: str = ""
    workspace: str
    model: str
    approval_mode: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def payload_must_be_json_safe(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not _json_safe(value):
            raise ValueError("log payload must be JSON-serializable")
        return value

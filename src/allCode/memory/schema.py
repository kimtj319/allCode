"""Memory data contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator

from allCode.core.models import CoreModel
from allCode.memory.redaction import redact_text

MemoryScope = Literal["global", "project", "directory", "session"]
MemoryKind = Literal[
    "instruction",
    "preference",
    "constraint",
    "workflow",
    "project_fact",
    "verification_command",
    "known_landmine",
    "recent_target",
    "repo_summary",
]
TargetType = Literal["file", "directory", "class", "function", "test", "command"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryItem(CoreModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    scope: MemoryScope
    kind: MemoryKind
    text: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    source_session_id: str | None = None
    applies_to: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    approved: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("text")
    @classmethod
    def redact_memory_text(cls, value: str) -> str:
        return redact_text(value.strip())


class RecentTarget(CoreModel):
    path: str
    symbol: str | None = None
    target_type: TargetType
    summary: str = ""
    turn_id: str
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("summary")
    @classmethod
    def redact_summary(cls, value: str) -> str:
        return redact_text(value.strip())


class RepoMapEntry(CoreModel):
    path: str
    language: str | None = None
    definitions: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    symbols: list[dict[str, object]] = Field(default_factory=list)
    imports_detail: list[dict[str, object]] = Field(default_factory=list)
    references_detail: list[dict[str, object]] = Field(default_factory=list)
    analysis_backend: str = ""
    analysis_quality: dict[str, object] = Field(default_factory=dict)
    summary: str = ""
    score: float = 0.0
    mtime: float | None = None


class ContextSection(CoreModel):
    name: str
    priority: int
    token_estimate: int
    content: str
    source: str
    section_type: str = "memory"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)

"""Codex-style transcript cell models.

The UI keeps committed transcript cells separate from the currently streaming
assistant cell. This avoids rewriting the whole transcript for every token and
lets the composer remain independent from answer rendering.
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import Field

from allCode.core.models import CoreModel

CellKind = Literal[
    "user",
    "assistant",
    "assistant_stream",
    "tool",
    "approval",
    "status",
    "error",
    "validation",
    "diff",
]


class TranscriptCell(CoreModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: CellKind
    content: str = ""
    title: str = ""
    transient: bool = False
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    def with_content(self, content: str) -> "TranscriptCell":
        return self.model_copy(update={"content": content})

    def append(self, delta: str) -> "TranscriptCell":
        return self.with_content(self.content + delta)


def user_cell(content: str) -> TranscriptCell:
    return TranscriptCell(kind="user", title="User", content=content)


def assistant_cell(content: str) -> TranscriptCell:
    return TranscriptCell(kind="assistant", title="allCode", content=content)


def streaming_assistant_cell(content: str = "") -> TranscriptCell:
    return TranscriptCell(kind="assistant_stream", title="allCode", content=content, transient=True)


def tool_cell(content: str, *, title: str = "Tool") -> TranscriptCell:
    return TranscriptCell(kind="tool", title=title, content=content)


def status_cell(content: str, *, title: str = "Status") -> TranscriptCell:
    return TranscriptCell(kind="status", title=title, content=content)


def error_cell(content: str, *, title: str = "Error") -> TranscriptCell:
    return TranscriptCell(kind="error", title=title, content=content)


def cell_to_legacy_block(cell: TranscriptCell) -> str:
    role = {
        "user": "user",
        "assistant": "allCode",
        "assistant_stream": "allCode",
        "tool": "tool",
        "approval": "approval",
        "status": "status",
        "validation": "status",
        "error": "error",
        "diff": "tool",
    }.get(cell.kind, "status")
    return format_legacy_block(role, cell.content)


def format_legacy_block(role: str, content: str) -> str:
    label = {
        "user": "USER",
        "allCode": "ALLCODE",
        "tool": "TOOL",
        "approval": "APPROVAL",
        "error": "ERROR",
        "status": "STATUS",
    }.get(role, role.strip().upper() or "STATUS")
    body = "\n".join(f"  {line}" if line else "" for line in content.split("\n"))
    return f"{label}\n{body}".rstrip("\n")

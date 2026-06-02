"""Logical tool action accounting for requested, executed, and reused calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from allCode.core.models import ToolCall

ToolActionStatus = Literal["requested", "executed", "reused", "suppressed", "schema_denied", "policy_denied"]


@dataclass(frozen=True)
class ToolActionRecord:
    call_id: str
    tool_name: str
    status: ToolActionStatus
    target: str = ""


@dataclass
class ToolActionLedger:
    """Separates model requests from actual executable tool actions."""

    records: list[ToolActionRecord] = field(default_factory=list)

    def record(self, tool_call: ToolCall, status: ToolActionStatus) -> None:
        self.records.append(
            ToolActionRecord(
                call_id=tool_call.id,
                tool_name=tool_call.name,
                status=status,
                target=_target_from_arguments(tool_call.arguments),
            )
        )

    def count(self, status: ToolActionStatus) -> int:
        return sum(1 for record in self.records if record.status == status)


def _target_from_arguments(arguments: dict) -> str:
    for key in ("file_path", "path", "query", "command", "url"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""

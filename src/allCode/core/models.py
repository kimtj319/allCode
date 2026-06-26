"""Provider-neutral data models shared across allCode layers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["system", "user", "assistant", "tool"]
AgentMode = Literal["all_rounder", "router_planner"]
TurnPhase = Literal[
    "created",
    "routing",
    "context",
    "model",
    "tools",
    "recovery",
    "final",
    "failed",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe(value: Any) -> bool:
    if value is None or isinstance(value, str | int | float | bool):
        return True
    if isinstance(value, list):
        return all(_json_safe(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_safe(item) for key, item in value.items())
    return False


class CoreModel(BaseModel):
    """Base model that keeps core contracts strict."""

    model_config = ConfigDict(extra="forbid")


class TokenUsage(CoreModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @field_validator("prompt_tokens", "completion_tokens", "total_tokens")
    @classmethod
    def require_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("token counts must be non-negative")
        return value


class WorkspaceRef(CoreModel):
    root: str
    writable: bool = True
    label: str | None = None

    @field_validator("root")
    @classmethod
    def require_root(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("workspace root must not be empty")
        return stripped


class ToolCall(CoreModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("arguments")
    @classmethod
    def arguments_must_be_json_safe(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not _json_safe(value):
            raise ValueError("tool arguments must be JSON-serializable")
        return value


class ToolResult(CoreModel):
    call_id: str
    name: str
    ok: bool
    content: str = ""
    error: str | None = None
    error_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_final: bool = False

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_json_safe(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not _json_safe(value):
            raise ValueError("metadata must be JSON-serializable")
        return value


class Message(CoreModel):
    role: Role
    content: str = ""
    # Optional image attachments as data URLs ("data:image/png;base64,...").
    # Sent as multimodal content blocks to vision-capable models.
    images: list[str] = Field(default_factory=list)
    # Assistant reasoning/analysis channel (gpt-oss harmony `reasoning_content`).
    # Carried so it can be replayed to the model on the next request — required
    # for reliable multi-turn tool use with gpt-oss-class models.
    reasoning: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utc_now)

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_json_safe(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not _json_safe(value):
            raise ValueError("metadata must be JSON-serializable")
        return value


class TurnInput(CoreModel):
    user_prompt: str
    workspace: WorkspaceRef
    mode: AgentMode = "all_rounder"
    session_id: str = Field(default_factory=lambda: uuid4().hex)
    images: list[str] = Field(default_factory=list)
    # Plan mode (Claude Code-style): read-only investigation that ends in an
    # implementation plan instead of edits. Lets the loop produce a plan answer
    # rather than the read-only structure summary when rounds are exhausted.
    plan_mode: bool = False

    @field_validator("user_prompt")
    @classmethod
    def require_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user prompt must not be empty")
        return value


class TurnState(CoreModel):
    turn_id: str = Field(default_factory=lambda: uuid4().hex)
    phase: TurnPhase = "created"
    messages: list[Message] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    created_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None

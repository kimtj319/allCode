"""Configuration schema for allCode."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictConfigModel(BaseModel):
    """Base config model that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid")


class ModelConfig(StrictConfigModel):
    model_name: str = "gpt-4o-mini"
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: int = 120
    max_output_tokens: int = 8192

    @field_validator("model_name", "api_key_env")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped

    @field_validator("timeout_seconds", "max_output_tokens")
    @classmethod
    def require_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value


class WorkspaceConfig(StrictConfigModel):
    root: str = "."
    extra_roots: list[str] = Field(default_factory=list)
    sandbox_enabled: bool = True

    @field_validator("root")
    @classmethod
    def require_workspace_root(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("workspace root must not be empty")
        return stripped

    def resolved_root(self) -> Path:
        return Path(self.root).expanduser().resolve()


class ApprovalConfig(StrictConfigModel):
    mode: Literal["ask", "auto", "rules"] = "ask"
    session_allow: list[str] = Field(default_factory=list)


class WebConfig(StrictConfigModel):
    search_url: str | None = None
    api_key_env: str | None = None
    timeout_seconds: int = 15

    @field_validator("search_url", "api_key_env")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("timeout_seconds")
    @classmethod
    def require_positive_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value


class AppConfig(StrictConfigModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    web: WebConfig = Field(default_factory=WebConfig)

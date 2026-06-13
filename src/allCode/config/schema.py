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
    extra_body: dict[str, object] = Field(default_factory=dict)

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
    backend: Literal["disabled", "http_json", "searxng", "duckduckgo_html"] = "duckduckgo_html"
    search_url: str | None = "https://html.duckduckgo.com/html/"
    api_key_env: str | None = None
    timeout_seconds: int = 15
    default_language: str = "ko-KR"
    default_categories: list[str] = Field(default_factory=lambda: ["general"])

    @field_validator("search_url", "api_key_env", "default_language")
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


class SourceIntelligenceConfig(StrictConfigModel):
    mode: Literal["off", "ast", "ast_lsp", "auto"] = "auto"
    lsp_enabled: bool = False
    lsp_timeout_ms: int = 1000
    servers: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("lsp_timeout_ms")
    @classmethod
    def require_positive_lsp_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value


class MCPServerConfig(StrictConfigModel):
    """A Model Context Protocol stdio server allCode launches and exposes as tools."""

    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("name", "command")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("value must be non-empty")
        return value.strip()


class MCPConfig(StrictConfigModel):
    servers: list[MCPServerConfig] = Field(default_factory=list)
    startup_timeout_ms: int = 8000

    @field_validator("startup_timeout_ms")
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
    source_intelligence: SourceIntelligenceConfig = Field(default_factory=SourceIntelligenceConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)


class ConfigFileSource(StrictConfigModel):
    path: str
    loaded: bool = False
    source_type: Literal["user", "project", "launch"]


class DotenvSource(StrictConfigModel):
    path: str
    loaded_keys: list[str] = Field(default_factory=list)


class ConfigSourceReport(StrictConfigModel):
    """Redacted report of how runtime configuration was resolved."""

    config_files: list[ConfigFileSource] = Field(default_factory=list)
    dotenv_files: list[DotenvSource] = Field(default_factory=list)
    env_overrides: list[str] = Field(default_factory=list)
    cli_overrides: list[str] = Field(default_factory=list)
    workspace_root: str
    model_name: str
    base_url: str | None = None
    api_key_env: str
    api_key_present: bool = False
    approval_mode: str
    web_backend: str
    web_search_host: str | None = None
    launch_config_fallback_used: bool = False

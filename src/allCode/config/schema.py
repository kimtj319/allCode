"""Configuration schema for allCode."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    # Optional higher-performance model used only for code implementation,
    # editing, and repair (the generation workflow editor). Routing, summary,
    # planning, and general reasoning keep `model_name`. When unset, `model_name`
    # is used everywhere (backward compatible).
    implementation_model_name: str | None = None

    @field_validator("model_name", "api_key_env")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped

    @field_validator("implementation_model_name")
    @classmethod
    def require_non_empty_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("implementation_model_name must not be empty when set")
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
    # OS-level confinement for run_command/run_tests, enforced by macOS
    # sandbox-exec or Linux bwrap. "workspace-write" allows reads + network but
    # blocks writes outside the workspace and temp dirs; "read-only" additionally
    # blocks workspace writes (temp only); "off" keeps the prior behavior
    # (path-confinement + approval only). No-op when the backend is unavailable.
    shell_sandbox: Literal["off", "read-only", "workspace-write"] = "off"

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
    # Per-path / per-command permission rules. Each entry is "Tool" or
    # "Tool(glob)" where Tool is an allCode tool name or a group (Bash, Edit,
    # Write, Read). deny wins over allow; allow auto-approves; unmatched calls
    # fall through to `mode`. e.g. allow: ["Bash(npm run test*)", "Write(src/**)"]
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)
    # Plan mode: present the generation plan and wait for approval before any
    # file is written. Off by default (the workflow proceeds straight to code).
    plan_mode: bool = False


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
    """A Model Context Protocol server allCode exposes as tools.

    ``transport`` selects how allCode reaches the server: ``stdio`` launches
    ``command``/``args`` as a child process; ``http`` (a.k.a. Streamable HTTP /
    SSE) connects to ``url`` over JSON-RPC.
    """

    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("value must be non-empty")
        return value.strip()

    @field_validator("transport")
    @classmethod
    def require_known_transport(cls, value: str) -> str:
        normalized = (value or "stdio").strip().lower()
        if normalized not in {"stdio", "http", "sse"}:
            raise ValueError("transport must be one of: stdio, http, sse")
        return normalized

    @model_validator(mode="after")
    def require_transport_target(self) -> "MCPServerConfig":
        if self.transport == "stdio":
            if not self.command.strip():
                raise ValueError("stdio MCP server requires a command")
        elif not (self.url or "").strip():
            raise ValueError("http/sse MCP server requires a url")
        return self


class MCPConfig(StrictConfigModel):
    servers: list[MCPServerConfig] = Field(default_factory=list)
    startup_timeout_ms: int = 8000

    @field_validator("startup_timeout_ms")
    @classmethod
    def require_positive_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value


class HookSpec(StrictConfigModel):
    # Glob matched against the tool name ("*" = all). command runs via the shell
    # with ALLCODE_TOOL_NAME / ALLCODE_TOOL_ARGS / ALLCODE_TOOL_OK in the env.
    match: str = "*"
    command: str
    timeout_seconds: int = 10

    @field_validator("command")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("hook command must be non-empty")
        return value


class HooksConfig(StrictConfigModel):
    # pre_tool hooks run before a tool; a non-zero exit blocks the tool.
    # post_tool hooks run after a tool (observe-only).
    pre_tool: list[HookSpec] = Field(default_factory=list)
    post_tool: list[HookSpec] = Field(default_factory=list)
    # user_prompt_submit hooks run before a turn (env ALLCODE_USER_PROMPT); a
    # non-zero exit blocks the turn with the hook's stderr as the reason, and any
    # stdout is injected into the turn as extra context (Claude-Code-style).
    user_prompt_submit: list[HookSpec] = Field(default_factory=list)
    # stop hooks run after a turn finishes (observe-only; env ALLCODE_TURN_STATUS,
    # ALLCODE_FINAL_ANSWER) — e.g. auto-format, lint, or notify.
    stop: list[HookSpec] = Field(default_factory=list)
    # session_start hooks run once when a session begins (env ALLCODE_SESSION_ID,
    # ALLCODE_WORKSPACE). A non-zero exit is ignored (observe-only); stdout is
    # injected as session-wide context for every turn — e.g. surface the current
    # branch, open tickets, or environment notes to the model.
    session_start: list[HookSpec] = Field(default_factory=list)


class GitConfig(StrictConfigModel):
    # When true, allCode commits file changes after a successful turn (marked so
    # /undo can revert only allCode's own commits). Off by default to avoid
    # touching the user's history unexpectedly.
    auto_commit: bool = False


class UIConfig(StrictConfigModel):
    # When true, the model's reasoning/thought channel is streamed to the UI
    # (dimmed) instead of being discarded. Toggle at runtime with /thinking.
    show_thinking: bool = False


class AgentConfig(StrictConfigModel):
    # Unified agent loop (Codex/Claude-style): one ReAct loop with the full
    # toolset always exposed and the model deciding which tools to use, instead
    # of pre-classifying into a RouteKind that locks the tool set and pipeline.
    # Rolled out behind this flag; see plan/74_unified_agent_loop_refactor.md.
    unified_loop: bool = False


class AppConfig(StrictConfigModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    source_intelligence: SourceIntelligenceConfig = Field(default_factory=SourceIntelligenceConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)


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
    implementation_model_name: str | None = None
    base_url: str | None = None
    api_key_env: str
    api_key_present: bool = False
    approval_mode: str
    web_backend: str
    web_search_host: str | None = None
    launch_config_fallback_used: bool = False

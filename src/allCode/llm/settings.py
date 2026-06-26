"""Model call settings shared by LLM adapters."""

from __future__ import annotations

from pydantic import Field

from allCode.config.schema import AppConfig
from allCode.core.models import CoreModel


class ModelSettings(CoreModel):
    model_name: str
    base_url: str | None = None
    api_key_env: str
    timeout_seconds: int = 120
    max_output_tokens: int = 16384
    context_window_tokens: int = 0
    temperature: float = 0.0
    # gpt-oss-style reasoning effort (low|medium|high). None = leave to the server
    # default. Routed per turn: deeper reasoning for code/analysis turns.
    reasoning_effort: str | None = None
    # Edit-format model-awareness (OFF by default). When True, ordinary mutation
    # turns expose only write_file (whole-file rewrite), not patch_file — weaker
    # models apply diffs less reliably (Aider). Pending A/B measurement.
    prefer_whole_file_edits: bool = False
    extra_body: dict[str, object] = Field(default_factory=dict)

    @classmethod
    def from_config(cls, config: AppConfig) -> "ModelSettings":
        return cls(
            model_name=config.model.model_name,
            base_url=config.model.base_url,
            api_key_env=config.model.api_key_env,
            timeout_seconds=config.model.timeout_seconds,
            max_output_tokens=config.model.max_output_tokens,
            context_window_tokens=config.model.context_window_tokens,
            reasoning_effort=getattr(config.model, "reasoning_effort", None),
            prefer_whole_file_edits=getattr(config.model, "prefer_whole_file_edits", False),
            extra_body=dict(config.model.extra_body),
        )

    @classmethod
    def implementation_from_config(cls, config: AppConfig) -> "ModelSettings":
        """Settings for the code-implementation/editor role. Uses the optional
        higher-performance ``implementation_model_name`` when configured, else the
        same model as :meth:`from_config` (backward compatible)."""

        settings = cls.from_config(config)
        impl_model = config.model.implementation_model_name
        if impl_model and impl_model != settings.model_name:
            return settings.model_copy(update={"model_name": impl_model})
        return settings


class ToolSchema(CoreModel):
    name: str
    description: str = ""
    parameters: dict[str, object] = Field(default_factory=dict)

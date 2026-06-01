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
    max_output_tokens: int = 8192
    temperature: float = 0.0

    @classmethod
    def from_config(cls, config: AppConfig) -> "ModelSettings":
        return cls(
            model_name=config.model.model_name,
            base_url=config.model.base_url,
            api_key_env=config.model.api_key_env,
            timeout_seconds=config.model.timeout_seconds,
            max_output_tokens=config.model.max_output_tokens,
        )


class ToolSchema(CoreModel):
    name: str
    description: str = ""
    parameters: dict[str, object] = Field(default_factory=dict)

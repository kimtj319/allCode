"""LLM client selection for runtime execution."""

from __future__ import annotations

from allCode.config.schema import AppConfig
from allCode.llm.adapters.openai_compatible import OpenAICompatibleClient
from allCode.llm.client import LLMClient


def uses_live_llm(config: AppConfig) -> bool:
    """Return whether runtime execution will use a real provider adapter."""

    return True


def create_llm_client(config: AppConfig) -> LLMClient:
    """Create the provider-neutral LLM client for the supplied config."""

    return OpenAICompatibleClient()

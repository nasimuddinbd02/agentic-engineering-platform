"""Provider selection - the single place that names a vendor."""

from __future__ import annotations

from core.config import Settings, get_settings
from core.errors import ConfigurationError
from llm.base import LLMProvider


def build_llm_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    provider = settings.llm_provider.lower()

    if provider in ("anthropic", "claude"):
        from llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=settings.llm_api_key or None,
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            effort=settings.llm_effort,
        )

    if provider == "scripted":
        from llm.scripted_provider import ScriptedLLMProvider

        return ScriptedLLMProvider()

    raise ConfigurationError(f"unknown LLM_PROVIDER: {settings.llm_provider}")

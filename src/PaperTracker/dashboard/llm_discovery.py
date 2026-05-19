"""Helpers for discovering LLM provider compatibility and model lists."""

from __future__ import annotations

from dataclasses import dataclass

from PaperTracker.llm.client import LLMApiClient


@dataclass(frozen=True, slots=True)
class LLMDiscoveryResult:
    """Detected LLM provider information for dashboard settings."""

    provider: str
    models: tuple[str, ...]


def discover_llm_provider_and_models(*, base_url: str, api_key: str) -> LLMDiscoveryResult:
    """Detect compatible provider type and available models for one endpoint."""
    client = LLMApiClient(
        base_url=base_url,
        api_key=api_key,
        timeout=20,
        max_retries=0,
    )
    models = tuple(client.list_models())
    return LLMDiscoveryResult(
        provider="openai-compat",
        models=models,
    )

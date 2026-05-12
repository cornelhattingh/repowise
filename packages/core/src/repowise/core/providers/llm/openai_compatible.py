"""OpenAI-compatible LLM provider for local/self-hosted chat servers.

Supports any OpenAI-compatible chat API endpoint (Ollama, LocalAI, vLLM, etc.)
by wrapping the OpenAIProvider with flexible environment variable fallbacks.

Environment Variables (in priority order):
    OPENAI_COMPATIBLE_BASE_URL   → base_url for the compatible server
    OPENAI_BASE_URL             → fallback base_url
    OPENAI_COMPATIBLE_API_KEY   → API key for the compatible server
    OPENAI_API_KEY              → fallback API key
    (defaults to "none" placeholder for local servers without auth)

Usage:
    # Ollama example
    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",
        model="llama3.2"
    )
    response = await provider.generate(
        system_prompt="You are a helpful assistant.",
        user_prompt="Hello!"
    )

    # LocalAI example
    provider = OpenAICompatibleProvider(
        base_url="http://localhost:8080/v1",
        model="gpt-3.5-turbo"
    )
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from repowise.core.providers.llm.openai import OpenAIProvider

if TYPE_CHECKING:
    from repowise.core.generation.cost_tracker import CostTracker
    from repowise.core.rate_limiter import RateLimiter


class OpenAICompatibleProvider(OpenAIProvider):
    """OpenAI-compatible chat provider adapter for local/self-hosted servers.

    Extends OpenAIProvider with flexible fallback logic for base_url and api_key,
    allowing use with local servers (Ollama, LocalAI, etc.) that may not require
    authentication.

    Args:
        api_key:      API key. Falls back to OPENAI_COMPATIBLE_API_KEY, OPENAI_API_KEY,
                      or uses "none" placeholder for local keyless servers.
        model:        Model identifier. Default: "llama3.2" (good for Ollama).
        base_url:     API endpoint URL. Falls back to OPENAI_COMPATIBLE_BASE_URL,
                      OPENAI_BASE_URL, or None (uses OpenAI's default).
        rate_limiter: Optional RateLimiter instance.
        cost_tracker: Optional CostTracker instance.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "llama3.2",
        base_url: str | None = None,
        rate_limiter: RateLimiter | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        # Resolve base_url with fallback chain
        resolved_base_url = (
            base_url
            or os.environ.get("OPENAI_COMPATIBLE_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
        )

        # Resolve api_key with fallback chain
        resolved_api_key = (
            api_key
            or os.environ.get("OPENAI_COMPATIBLE_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )

        # If api_key ends up empty, use "none" placeholder to satisfy OpenAI SDK
        # and bypass parent's key validation
        if not resolved_api_key:
            resolved_api_key = "none"

        # Delegate to parent OpenAIProvider
        # We bypass the parent's ProviderError check by always providing a key
        super().__init__(
            api_key=resolved_api_key,
            model=model,
            base_url=resolved_base_url,
            rate_limiter=rate_limiter,
            cost_tracker=cost_tracker,
        )

    @property
    def provider_name(self) -> str:
        """Return 'openai_compatible' to distinguish from base OpenAI provider."""
        return "openai_compatible"

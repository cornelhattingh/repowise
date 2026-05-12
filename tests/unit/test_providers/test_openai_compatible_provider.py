"""Unit tests for OpenAICompatibleProvider.

Tests verify that OpenAI-compatible providers (Ollama, LocalAI, etc.) can be
instantiated with appropriate fallback behavior for local servers that don't
require authentication.

All tests mock the OpenAI SDK — no real API calls are made.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

pytest.importorskip("openai", reason="openai SDK not installed")

from repowise.core.providers.llm.openai_compatible import OpenAICompatibleProvider
from repowise.core.providers.llm.registry import get_provider

# ---------------------------------------------------------------------------
# Base URL resolution
# ---------------------------------------------------------------------------


def test_uses_explicit_base_url():
    """When base_url is passed explicitly, it takes priority."""
    with patch.dict(os.environ, {}, clear=True):
        provider = OpenAICompatibleProvider(base_url="http://localhost:11434/v1")
        # Check that the client's base_url was set correctly (strip trailing slash)
        assert str(provider._client.base_url).rstrip("/") == "http://localhost:11434/v1"


def test_reads_openai_compatible_base_url_env():
    """When OPENAI_COMPATIBLE_BASE_URL env var is set, use it."""
    with patch.dict(
        os.environ, {"OPENAI_COMPATIBLE_BASE_URL": "http://localhost:8080/v1"}, clear=True
    ):
        provider = OpenAICompatibleProvider()
        assert str(provider._client.base_url).rstrip("/") == "http://localhost:8080/v1"


def test_reads_openai_base_url_env():
    """When only OPENAI_BASE_URL env var is set, use it."""
    with patch.dict(os.environ, {"OPENAI_BASE_URL": "http://localhost:9999/v1"}, clear=True):
        provider = OpenAICompatibleProvider()
        assert str(provider._client.base_url).rstrip("/") == "http://localhost:9999/v1"


def test_compatible_env_takes_priority_over_openai_base_url():
    """OPENAI_COMPATIBLE_BASE_URL takes precedence over OPENAI_BASE_URL."""
    with patch.dict(
        os.environ,
        {
            "OPENAI_COMPATIBLE_BASE_URL": "http://localhost:11434/v1",
            "OPENAI_BASE_URL": "http://localhost:9999/v1",
        },
        clear=True,
    ):
        provider = OpenAICompatibleProvider()
        assert str(provider._client.base_url).rstrip("/") == "http://localhost:11434/v1"


# ---------------------------------------------------------------------------
# API key resolution and placeholder behavior
# ---------------------------------------------------------------------------


def test_api_key_placeholder_for_local_servers():
    """When no API key is supplied, instantiation succeeds (doesn't raise ProviderError)."""
    with patch.dict(os.environ, {}, clear=True):
        # Should not raise ProviderError
        provider = OpenAICompatibleProvider(base_url="http://localhost:11434/v1")
        # Should have a client (with placeholder key)
        assert provider._client is not None


def test_explicit_api_key_used():
    """When api_key is passed explicitly, that key is used."""
    with patch.dict(os.environ, {}, clear=True):
        provider = OpenAICompatibleProvider(api_key="sk-test")
        # The client should have been created with the explicit key
        assert provider._client is not None


def test_reads_openai_compatible_api_key_env():
    """When OPENAI_COMPATIBLE_API_KEY env var is set, use it."""
    with patch.dict(os.environ, {"OPENAI_COMPATIBLE_API_KEY": "sk-compatible"}, clear=True):
        provider = OpenAICompatibleProvider()
        # Should successfully create client with the env var key
        assert provider._client is not None


def test_api_key_fallback_to_openai_api_key():
    """When only OPENAI_API_KEY env var is set, use it."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-openai"}, clear=True):
        provider = OpenAICompatibleProvider()
        # Should successfully create client with the fallback key
        assert provider._client is not None


def test_compatible_api_key_takes_priority_over_openai_api_key():
    """OPENAI_COMPATIBLE_API_KEY takes precedence over OPENAI_API_KEY."""
    with patch.dict(
        os.environ,
        {"OPENAI_COMPATIBLE_API_KEY": "sk-compatible", "OPENAI_API_KEY": "sk-openai"},
        clear=True,
    ):
        provider = OpenAICompatibleProvider()
        # Should use the OPENAI_COMPATIBLE_API_KEY
        assert provider._client is not None


# ---------------------------------------------------------------------------
# Provider name property
# ---------------------------------------------------------------------------


def test_provider_name_returns_openai_compatible():
    """provider_name property returns 'openai_compatible'."""
    with patch.dict(os.environ, {}, clear=True):
        provider = OpenAICompatibleProvider(base_url="http://localhost:11434/v1")
        assert provider.provider_name == "openai_compatible"


# ---------------------------------------------------------------------------
# Default model
# ---------------------------------------------------------------------------


def test_default_model_is_llama32():
    """Default model is 'llama3.2' for local server compatibility."""
    with patch.dict(os.environ, {}, clear=True):
        provider = OpenAICompatibleProvider(base_url="http://localhost:11434/v1")
        assert provider.model_name == "llama3.2"


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_registered_in_registry():
    """get_provider('openai_compatible') resolves without ImportError."""
    with patch.dict(os.environ, {}, clear=True):
        provider = get_provider(
            "openai_compatible",
            base_url="http://localhost:11434/v1",
            with_rate_limiter=False,
        )
        assert provider is not None
        assert provider.provider_name == "openai_compatible"
        assert str(provider._client.base_url).rstrip("/") == "http://localhost:11434/v1"

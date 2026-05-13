"""Unit tests for OpenAI-compatible LLM provider CLI integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from repowise.cli.helpers import resolve_provider, validate_provider_config


@pytest.fixture(autouse=True)
def clear_provider_env(monkeypatch):
    """Clear all provider-related env vars before each test."""
    for var in [
        "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
        "OPENAI_API_KEY", "OPENAI_BASE_URL",
        "OPENAI_COMPATIBLE_BASE_URL", "OPENAI_COMPATIBLE_API_KEY",
        "OPENROUTER_API_KEY",
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_BASE_URL",
        "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL",
        "OLLAMA_BASE_URL",
        "LITELLM_API_KEY", "LITELLM_BASE_URL", "LITELLM_API_BASE",
        "REPOWISE_PROVIDER",
    ]:
        monkeypatch.delenv(var, raising=False)


class TestResolveProviderAutoDetect:
    """Test auto-detection of openai_compatible provider."""

    def test_resolve_provider_compatible_base_url_auto_detects(self, monkeypatch, tmp_path):
        """With OPENAI_COMPATIBLE_BASE_URL set and no other provider keys, should auto-detect openai_compatible."""
        # Set OPENAI_COMPATIBLE_BASE_URL
        monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:11434/v1")

        # Auto-detect (no explicit provider)
        provider = resolve_provider(None, None, tmp_path)
        assert provider.provider_name == "openai_compatible"
        # Check internal client base_url
        assert provider._client.base_url is not None
        assert str(provider._client.base_url) == "http://localhost:11434/v1/"

    def test_resolve_provider_compatible_base_url_takes_priority_over_openai_key(
        self, monkeypatch, tmp_path
    ):
        """With both OPENAI_COMPATIBLE_BASE_URL and OPENAI_API_KEY set, openai_compatible should win."""
        monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

        # Auto-detect should prefer openai_compatible over openai
        provider = resolve_provider(None, None, tmp_path)
        assert provider.provider_name == "openai_compatible"
        # Check internal client base_url
        assert provider._client.base_url is not None
        assert str(provider._client.base_url) == "http://localhost:11434/v1/"


class TestResolveProviderExplicit:
    """Test explicit provider selection for openai_compatible."""

    def test_resolve_provider_explicit_openai_compatible(self, monkeypatch, tmp_path):
        """Explicit --provider openai_compatible should work."""
        monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "test-key")

        provider = resolve_provider("openai_compatible", None, tmp_path)
        assert provider.provider_name == "openai_compatible"
        # Check internal client base_url
        assert provider._client.base_url is not None
        assert str(provider._client.base_url) == "http://localhost:11434/v1/"

    def test_resolve_provider_explicit_openai_compatible_with_model(self, monkeypatch, tmp_path):
        """Explicit provider with model override."""
        monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:11434/v1")

        provider = resolve_provider("openai_compatible", "llama3.2", tmp_path)
        assert provider.provider_name == "openai_compatible"
        assert provider._model == "llama3.2"

    def test_resolve_provider_explicit_openai_compatible_keyless(self, monkeypatch, tmp_path):
        """openai_compatible should work without an API key (keyless servers)."""
        monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        provider = resolve_provider("openai_compatible", None, tmp_path)
        assert provider.provider_name == "openai_compatible"
        # Provider should handle None api_key gracefully


class TestValidateProviderConfig:
    """Test provider validation for openai_compatible."""

    def test_validate_warns_when_no_base_url_set(self, monkeypatch):
        """openai_compatible should warn when neither base URL is set."""
        # No base URLs set (cleared by autouse fixture)
        warnings = validate_provider_config("openai_compatible")
        assert len(warnings) > 0
        assert any("OPENAI_COMPATIBLE_BASE_URL" in w for w in warnings)
        assert any("OPENAI_BASE_URL" in w for w in warnings)
        assert any("fall back" in w or "fallback" in w for w in warnings)

    def test_validate_no_warnings_when_compatible_base_url_set(self, monkeypatch):
        """With OPENAI_COMPATIBLE_BASE_URL set, validation should pass."""
        monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:11434/v1")

        warnings = validate_provider_config("openai_compatible")
        assert warnings == []

    def test_validate_no_warnings_when_openai_base_url_set(self, monkeypatch):
        """With OPENAI_BASE_URL set, validation should also pass."""
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")

        warnings = validate_provider_config("openai_compatible")
        assert warnings == []


class TestServerCatalog:
    """Test provider_config.py server-side catalog and functions."""

    def test_server_catalog_includes_openai_compatible(self):
        """PROVIDER_CATALOG should include openai_compatible."""
        from repowise.server.provider_config import PROVIDER_CATALOG

        compatible_entry = None
        for entry in PROVIDER_CATALOG:
            if entry["id"] == "openai_compatible":
                compatible_entry = entry
                break

        assert compatible_entry is not None, "openai_compatible not found in PROVIDER_CATALOG"
        assert compatible_entry["name"] == "OpenAI-Compatible (Local/Custom)"
        assert compatible_entry["requires_key"] is False
        assert "OPENAI_COMPATIBLE_API_KEY" in compatible_entry["env_keys"]

    def test_server_base_url_resolution(self, monkeypatch):
        """_get_base_url_for_provider should resolve OPENAI_COMPATIBLE_BASE_URL."""
        from repowise.server.provider_config import _get_base_url_for_provider

        monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:11434/v1")

        base_url = _get_base_url_for_provider("openai_compatible")
        assert base_url == "http://localhost:11434/v1"

    def test_server_base_url_fallback_to_openai_base_url(self, monkeypatch):
        """_get_base_url_for_provider should fall back to OPENAI_BASE_URL."""
        from repowise.server.provider_config import _get_base_url_for_provider

        monkeypatch.delenv("OPENAI_COMPATIBLE_BASE_URL", raising=False)
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")

        base_url = _get_base_url_for_provider("openai_compatible")
        assert base_url == "http://localhost:11434/v1"

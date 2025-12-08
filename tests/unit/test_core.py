"""Unit tests for core modules."""

import os

import pytest
from config.settings import settings, EnvSettings

from olav.core.prompt_manager import PromptManager


def test_settings_defaults(monkeypatch):
    """Test default settings initialization."""
    # Clear environment to test true defaults
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL_NAME", raising=False)
    test_settings = EnvSettings(
        llm_api_key="test-key",
        netbox_token="test-token",
        device_password="test-password",
    )
    # Default is ollama for local development
    assert test_settings.llm_provider in ["openai", "ollama"]
    assert test_settings.device_password == "test-password"


def test_config_settings():
    """Test application config settings."""
    # Settings are loaded from .env
    assert settings.llm_temperature >= 0 and settings.llm_temperature <= 1
    assert settings.agent_max_tool_calls > 0
    assert isinstance(settings.enable_hitl, bool)


def test_llm_factory_openai():
    """Test LLM factory creates OpenAI model."""
    # This will fail without actual API key - mark as integration test
    pytest.skip("Requires API key configuration")


def test_prompt_manager_cache():
    """Test prompt manager caching."""
    pm = PromptManager()

    # Cache should be empty initially
    assert len(pm._cache) == 0

    # Reload should clear cache
    pm.reload()
    assert len(pm._cache) == 0


@pytest.mark.asyncio
async def test_opensearch_memory_search(opensearch_memory):
    """Test OpenSearch schema search."""
    # TODO: Implement with actual OpenSearch test container
    pytest.skip("Requires OpenSearch test container")

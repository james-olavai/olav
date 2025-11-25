"""Unit tests for core modules."""

import pytest

from config.settings import AgentConfig, LLMConfig
from olav.core.llm import LLMFactory
from olav.core.prompt_manager import PromptManager
from olav.core.settings import EnvSettings


def test_settings_defaults():
    """Test default settings initialization."""
    settings = EnvSettings(
        llm_api_key="test-key",
        netbox_token="test-token",
        device_password="test-password",
    )
    assert settings.llm_provider == "openai"
    assert settings.device_password == "test-password"
    assert settings.environment in ["local", "docker"]


def test_config_settings():
    """Test application config settings."""
    # Note: MODEL_NAME may vary based on .env configuration
    assert LLMConfig.MODEL_NAME in ["gpt-4-turbo", "x-ai/grok-4.1-fast", "gpt-4o-mini"]
    assert LLMConfig.TEMPERATURE == 0.2
    assert AgentConfig.MAX_ITERATIONS == 20
    assert AgentConfig.ENABLE_HITL is True


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

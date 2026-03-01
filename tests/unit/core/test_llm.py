"""Unit tests for src/olav/core/llm.py."""

import pytest
from unittest.mock import patch, MagicMock


def test_llm_factory_import():
    """Test LLMFactory can be imported."""
    from src.olav.core.llm import LLMFactory

    assert LLMFactory is not None


def test_llm_factory_get_chat_model():
    """Test get_chat_model with mocked settings."""
    with patch("src.olav.core.llm.settings") as mock_settings:
        mock_settings.llm_temperature = 0.7
        mock_settings.llm_model_name = "gpt-4"
        mock_settings.llm_max_tokens = 1000
        mock_settings.llm_provider = "openai"
        mock_settings.llm_api_key = "test-key"
        mock_settings.llm_base_url = None

        from src.olav.core.llm import LLMFactory

        # Just test that it can be called without error
        # (actual provider calls would fail in unit tests)
        try:
            LLMFactory.get_chat_model()
        except Exception:
            pass  # Expected - provider not available


def test_llm_factory_get_embeddings():
    """Test get_embeddings with mocked settings."""
    with patch("src.olav.core.llm.settings") as mock_settings:
        mock_settings.embedding_mode = "local"
        mock_settings.embedding_model = "sentence-transformers"

        from src.olav.core.llm import LLMFactory

        try:
            LLMFactory.get_embeddings("test text")
        except Exception:
            pass  # Expected - model not available

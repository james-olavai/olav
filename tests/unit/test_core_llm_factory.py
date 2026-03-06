"""Unit tests for olav/core/llm.py — v0.11.0 init_chat_model refactor.

The LLM factory was refactored in v0.11.0 to use LangChain's `init_chat_model`
for dynamic provider support instead of per-provider if-elif branches.
These tests target the actual implementation.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestLLMFactory:
    """Tests for LLMFactory — v0.11.0 init_chat_model implementation."""

    def test_factory_is_importable(self):
        """LLMFactory must be importable from canonical path."""
        from olav.core.llm import LLMFactory

        assert LLMFactory is not None
        assert callable(LLMFactory.get_chat_model)

    def test_get_chat_model_calls_init_chat_model(self):
        """get_chat_model must delegate to langchain.chat_models.init_chat_model."""
        from olav.core.llm import LLMFactory

        mock_model = MagicMock()
        with patch("olav.core.llm.init_chat_model", return_value=mock_model) as mock_init:
            result = LLMFactory.get_chat_model(model_name="test-model", temperature=0.5)
            mock_init.assert_called_once()
            call_kwargs = mock_init.call_args[1]
            assert call_kwargs["model"] == "test-model"
            assert call_kwargs["temperature"] == 0.5
            assert result is mock_model

    def test_get_chat_model_streaming_disabled(self):
        """Streaming must always be False for DeepAgents async compatibility."""
        from olav.core.llm import LLMFactory

        mock_model = MagicMock()
        with patch("olav.core.llm.init_chat_model", return_value=mock_model) as mock_init:
            LLMFactory.get_chat_model(model_name="test")
            call_kwargs = mock_init.call_args[1]
            assert call_kwargs.get("streaming") is False

    def test_get_chat_model_temperature_override(self):
        """Explicit temperature must override settings defaults."""
        from olav.core.llm import LLMFactory

        mock_model = MagicMock()
        with patch("olav.core.llm.init_chat_model", return_value=mock_model) as mock_init:
            LLMFactory.get_chat_model(model_name="test", temperature=0.0)
            call_kwargs = mock_init.call_args[1]
            assert call_kwargs["temperature"] == 0.0

    def test_get_chat_model_propagates_exception(self):
        """init_chat_model errors must propagate (not silently swallowed)."""
        from olav.core.llm import LLMFactory

        with patch("olav.core.llm.init_chat_model", side_effect=ValueError("bad model")):
            with pytest.raises(ValueError, match="bad model"):
                LLMFactory.get_chat_model(model_name="bad")

    def test_get_embeddings_local_mode(self):
        """get_embeddings in local mode uses sentence_transformers.SentenceTransformer."""
        from olav.core.llm import LLMFactory

        mock_st_instance = MagicMock()
        with patch("olav.core.config.get_embedding_config") as mock_cfg:
            mock_cfg.return_value.mode = "local"
            mock_cfg.return_value.local_model = "BAAI/bge-small-en-v1.5"
            mock_cfg.return_value.device = "cpu"
            mock_cfg.return_value.normalize_embeddings = True

            with patch("sentence_transformers.SentenceTransformer", return_value=mock_st_instance) as mock_st_cls:
                result = LLMFactory.get_embeddings()
                mock_st_cls.assert_called_once()
                assert result is not None
                assert hasattr(result, "embed_documents")
                assert hasattr(result, "embed_query")

    def test_get_embeddings_api_mode(self):
        """get_embeddings in api mode uses OpenAIEmbeddings."""
        from olav.core.llm import LLMFactory

        mock_emb = MagicMock()
        with patch("olav.core.config.get_embedding_config") as mock_cfg:
            mock_cfg.return_value.mode = "api"
            mock_cfg.return_value.model = "text-embedding-3-small"
            mock_cfg.return_value.api_key = "sk-test"
            mock_cfg.return_value.base_url = None

            with patch("langchain_openai.OpenAIEmbeddings", return_value=mock_emb) as mock_oe:
                result = LLMFactory.get_embeddings()
                mock_oe.assert_called_once()
                assert result is mock_emb


class TestLLMFactoryConnectivity:
    """Tests for LLMFactory.test_connectivity()."""

    def test_connectivity_returns_false_on_error(self):
        """test_connectivity returns False when model raises (never re-raises)."""
        from olav.core.llm import LLMFactory

        mock_model = MagicMock()
        mock_model.invoke.side_effect = ConnectionError("no network")

        with patch.object(LLMFactory, "get_chat_model", return_value=mock_model):
            result = LLMFactory.test_connectivity()
            assert result is False

    def test_connectivity_true_on_success(self):
        """test_connectivity returns True when invoke succeeds."""
        from olav.core.llm import LLMFactory

        mock_model = MagicMock()
        mock_model.invoke.return_value = MagicMock(content="OK")

        with patch.object(LLMFactory, "get_chat_model", return_value=mock_model):
            result = LLMFactory.test_connectivity()
            assert result is True


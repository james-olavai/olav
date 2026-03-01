import pytest
from unittest.mock import MagicMock


class TestContextCompression:
    def test_context_compressor_import(self):
        from olav.core.context_compression import ContextCompressor, create_context_compressor

        assert ContextCompressor is not None
        assert create_context_compressor is not None

    def test_create_context_compressor(self):
        from olav.core.context_compression import create_context_compressor

        compressor = create_context_compressor(max_tokens=2000)
        assert compressor.max_token_limit == 2000

    def test_add_user_message(self):
        from olav.core.context_compression import ContextCompressor

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Summary")

        compressor = ContextCompressor(llm=mock_llm, max_token_limit=1000)
        compressor.add_message("user", "Hello")

        messages = compressor.get_messages()
        assert len(messages) == 1

    def test_add_assistant_message(self):
        from olav.core.context_compression import ContextCompressor

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Summary")

        compressor = ContextCompressor(llm=mock_llm, max_token_limit=1000)
        compressor.add_message("assistant", "Hi there")

        messages = compressor.get_messages()
        assert len(messages) == 1

    def test_add_messages_batch(self):
        from olav.core.context_compression import ContextCompressor

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Summary")

        compressor = ContextCompressor(llm=mock_llm, max_token_limit=1000)

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
        ]
        compressor.add_messages(messages)

        assert len(compressor.get_messages()) == 3

    def test_get_context(self):
        from olav.core.context_compression import ContextCompressor

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Summary")

        compressor = ContextCompressor(llm=mock_llm, max_token_limit=1000)
        compressor.add_message("user", "Test message")

        context = compressor.get_context()
        assert "Test message" in context

    def test_clear_memory(self):
        from olav.core.context_compression import ContextCompressor

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Summary")

        compressor = ContextCompressor(llm=mock_llm, max_token_limit=1000)
        compressor.add_message("user", "Test")

        assert len(compressor.get_messages()) == 1

        compressor.clear()

        assert len(compressor.get_messages()) == 0

    def test_default_token_limit(self):
        from olav.core.context_compression import ContextCompressor, DEFAULT_MAX_TOKEN_LIMIT

        assert DEFAULT_MAX_TOKEN_LIMIT == 4000


class TestContextCompressionIntegration:
    def test_compression_preserves_summary(self):
        from olav.core.context_compression import ContextCompressor

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Past conversation summary")

        compressor = ContextCompressor(llm=mock_llm, max_token_limit=100)

        for i in range(25):
            compressor.add_message("user", f"Message {i}")

        compressor.compress()

        context = compressor.get_context()
        assert "summary" in context.lower() or "Past conversation" in context


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Unit tests for API server module.

Run: pytest tests/unit/test_api_server.py -v
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


class TestAPIServer:
    """Tests for src/olav/api/server.py"""

    def test_server_import(self):
        """Test server module can be imported."""
        from src.olav.api.server import app

        assert app is not None
        assert app.title == "OLAV API"

    def test_thread_create_model(self):
        """Test ThreadCreate model."""
        from src.olav.api.server import ThreadCreate

        thread = ThreadCreate(metadata={"key": "value"})
        assert thread.metadata == {"key": "value"}

    def test_run_stream_request_model(self):
        """Test RunStreamRequest model."""
        from src.olav.api.server import RunStreamRequest

        request = RunStreamRequest(input={"message": "hello"})
        assert request.input == {"message": "hello"}
        assert request.assistant_id == "olav-orchestrator"

    def test_message_input_model(self):
        """Test MessageInput model."""
        from src.olav.api.server import MessageInput

        msg = MessageInput(messages=[{"role": "user", "content": "hello"}])
        assert len(msg.messages) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

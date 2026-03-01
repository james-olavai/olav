"""Unit tests for src/olav/api/server.py."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from src.olav.api.server import app

client = TestClient(app)


def test_health():
    """Test /health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_create_thread():
    """Test /threads endpoint."""
    response = client.post("/threads", json={"metadata": {"user": "test"}})
    assert response.status_code == 200
    assert "thread_id" in response.json()
    assert response.json()["metadata"]["user"] == "test"


def test_search_threads():
    """Test /threads/search endpoint."""
    response = client.get("/threads/search")
    assert response.status_code == 200
    assert "threads" in response.json()


@pytest.mark.asyncio
async def test_stream_run():
    """Test /threads/{id}/runs/stream endpoint."""
    with patch("src.olav.api.server.get_agent") as mock_get_agent:
        mock_agent = MagicMock()
        mock_agent.graph.astream_events = MagicMock()

        async def mock_events(*args, **kwargs):
            yield {"event": "on_chat_model_stream", "data": {"chunk": "Hello"}}

        mock_agent.graph.astream_events.side_effect = mock_events
        mock_get_agent.return_value = mock_agent

        response = client.post(
            "/threads/test-thread/runs/stream",
            json={"input": {"messages": [{"role": "user", "content": "hi"}]}},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        # Note: TestClient doesn't support streaming responses easily in sync mode,
        # but it should return the full content.
        assert "Hello" in response.text


def test_threadless_stream():
    """Test /runs/stream endpoint."""
    with patch("src.olav.api.server.stream_run") as mock_stream:
        mock_stream.return_value = {"status": "ok"}
        response = client.post(
            "/runs/stream", json={"input": {"messages": [{"role": "user", "content": "hi"}]}}
        )
        # Since we mocked stream_run, it returns what we mocked
        assert response.json() == {"status": "ok"}

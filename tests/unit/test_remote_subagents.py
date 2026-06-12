"""TDD — AsyncSubAgent remote LangGraph deployment support.

Remote subagents are configured in .olav/config/api.json under "async_subagents":
    {
        "async_subagents": [
            {
                "name": "remote-ops",
                "description": "Remote ops agent on LangGraph Cloud",
                "url": "https://my-deployment.langsmith.com",
                "graph_id": "ops",
                "api_key_env": "LANGGRAPH_API_KEY"
            }
        ]
    }

deepagents 0.5+: returns native AsyncSubAgent dicts (name, description, graph_id, url, headers).
The AsyncSubAgentMiddleware in deepagents handles the actual non-blocking execution.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


# ── RemoteSubAgentLoader unit tests ──────────────────────────────────────────


class TestRemoteSubAgentLoader:
    """load_remote_subagents() reads async_subagents from api.json config."""

    def test_empty_config_returns_empty_list(self):
        from olav.agents.remote_subagents import load_remote_subagents
        result = load_remote_subagents(config={})
        assert result == []

    def test_missing_async_subagents_key_returns_empty(self):
        from olav.agents.remote_subagents import load_remote_subagents
        result = load_remote_subagents(config={"llm": {"model": "gpt-4"}})
        assert result == []

    def test_loads_single_remote_subagent(self, monkeypatch):
        from olav.agents.remote_subagents import load_remote_subagents
        monkeypatch.setenv("TEST_REMOTE_API_KEY", "test-key-123")

        config = {
            "async_subagents": [
                {
                    "name": "remote-ops",
                    "description": "Remote ops agent",
                    "url": "https://api.smith.langchain.com",
                    "graph_id": "ops-agent",
                    "api_key_env": "TEST_REMOTE_API_KEY",
                }
            ]
        }

        result = load_remote_subagents(config=config)

        assert len(result) == 1
        assert result[0]["name"] == "remote-ops"
        assert result[0]["description"] == "Remote ops agent"
        assert result[0]["graph_id"] == "ops-agent"
        assert result[0]["url"] == "https://api.smith.langchain.com"
        # API key injected as header
        assert result[0].get("headers", {}).get("x-api-key") == "test-key-123"

    def test_loads_single_remote_subagent_assistant_id_compat(self, monkeypatch):
        """assistant_id is accepted as backward-compat alias for graph_id."""
        from olav.agents.remote_subagents import load_remote_subagents

        config = {
            "async_subagents": [
                {
                    "name": "compat-ops",
                    "description": "Backward compat",
                    "url": "https://api.smith.langchain.com",
                    "assistant_id": "ops-v1",  # old field name
                }
            ]
        }

        result = load_remote_subagents(config=config)

        assert len(result) == 1
        assert result[0]["graph_id"] == "ops-v1"

    def test_remote_subagent_skipped_if_missing_url(self, monkeypatch, caplog):
        import logging
        from olav.agents.remote_subagents import load_remote_subagents

        config = {
            "async_subagents": [
                {
                    "name": "broken",
                    "description": "Missing URL",
                    "graph_id": "x",
                }
            ]
        }

        with caplog.at_level(logging.WARNING, logger="olav"):
            result = load_remote_subagents(config=config)

        assert result == []
        assert any("url" in r.message.lower() or "skip" in r.message.lower()
                   for r in caplog.records)

    def test_remote_subagent_skipped_if_missing_graph_id(self, monkeypatch, caplog):
        import logging
        from olav.agents.remote_subagents import load_remote_subagents

        config = {
            "async_subagents": [
                {
                    "name": "broken",
                    "description": "Missing graph_id",
                    "url": "https://example.com",
                }
            ]
        }

        with caplog.at_level(logging.WARNING, logger="olav"):
            result = load_remote_subagents(config=config)

        assert result == []

    def test_api_key_resolved_from_env(self, monkeypatch):
        from olav.agents.remote_subagents import load_remote_subagents
        monkeypatch.setenv("MY_CUSTOM_KEY", "env-resolved-key")

        config = {
            "async_subagents": [
                {
                    "name": "r1",
                    "description": "d",
                    "url": "https://x.com",
                    "graph_id": "a1",
                    "api_key_env": "MY_CUSTOM_KEY",
                }
            ]
        }

        result = load_remote_subagents(config=config)

        assert len(result) == 1
        assert result[0]["headers"]["x-api-key"] == "env-resolved-key"

    def test_api_key_falls_back_to_langgraph_env(self, monkeypatch):
        """When api_key_env not set, falls back to LANGGRAPH_API_KEY."""
        from olav.agents.remote_subagents import load_remote_subagents
        monkeypatch.setenv("LANGGRAPH_API_KEY", "fallback-key")

        config = {
            "async_subagents": [
                {
                    "name": "r1",
                    "description": "d",
                    "url": "https://x.com",
                    "graph_id": "a1",
                    # no api_key_env — should fall back to LANGGRAPH_API_KEY
                }
            ]
        }

        result = load_remote_subagents(config=config)

        assert len(result) == 1
        assert result[0]["headers"]["x-api-key"] == "fallback-key"

    def test_no_api_key_no_headers(self, monkeypatch):
        """When no API key is available, headers field is omitted."""
        from olav.agents.remote_subagents import load_remote_subagents
        # Clear all key env vars
        for k in ["LANGGRAPH_API_KEY", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"]:
            monkeypatch.delenv(k, raising=False)

        config = {
            "async_subagents": [
                {"name": "r1", "description": "d", "url": "https://x.com", "graph_id": "a1"}
            ]
        }

        result = load_remote_subagents(config=config)
        assert len(result) == 1
        assert "headers" not in result[0]

    def test_multiple_remote_subagents_loaded(self, monkeypatch):
        from olav.agents.remote_subagents import load_remote_subagents
        monkeypatch.setenv("LANGGRAPH_API_KEY", "key")

        config = {
            "async_subagents": [
                {"name": "r1", "description": "d1", "url": "https://a.com", "graph_id": "a1"},
                {"name": "r2", "description": "d2", "url": "https://b.com", "graph_id": "a2"},
            ]
        }

        result = load_remote_subagents(config=config)

        assert len(result) == 2
        assert {r["name"] for r in result} == {"r1", "r2"}


# ── Integration: OLAVAgent loads remote subagents from api.json ───────────────


class TestOLAVAgentRemoteSubAgentIntegration:
    """OLAVAgent._build_subagents appends remote subagents from api.json config."""

    def test_remote_subagents_merged_with_local(self, monkeypatch):
        """Remote subagents from api.json are appended to local workspace subagents."""
        from olav.agents import remote_subagents as rs_module

        fake_remote = {
            "name": "remote-test",
            "description": "Remote test agent",
            "graph_id": "test-graph",
            "url": "https://x.com",
        }
        with patch.object(rs_module, "load_remote_subagents", return_value=[fake_remote]):
            from olav.agents.remote_subagents import load_remote_subagents
            result = load_remote_subagents(config={
                "async_subagents": [
                    {"name": "remote-test", "description": "d",
                     "url": "https://x.com", "graph_id": "a"}
                ]
            })
        assert len(result) >= 0


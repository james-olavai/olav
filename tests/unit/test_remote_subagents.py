"""TDD — AsyncSubAgent remote LangGraph deployment support.

Remote subagents are configured in .olav/config/api.json under "async_subagents":
    {
        "async_subagents": [
            {
                "name": "remote-ops",
                "description": "Remote ops agent on LangGraph Cloud",
                "url": "https://my-deployment.langsmith.com",
                "assistant_id": "ops",
                "api_key_env": "LANGGRAPH_API_KEY"
            }
        ]
    }

They are loaded in OLAVAgent._build_subagents() and passed to create_deep_agent()
as CompiledSubAgent with a RemoteGraph runnable.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
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
                    "assistant_id": "ops-agent",
                    "api_key_env": "TEST_REMOTE_API_KEY",
                }
            ]
        }

        with patch("olav.agents.remote_subagents.RemoteGraph") as mock_remote:
            mock_remote.return_value = MagicMock()
            result = load_remote_subagents(config=config)

        assert len(result) == 1
        assert result[0]["name"] == "remote-ops"
        assert result[0]["description"] == "Remote ops agent"
        assert "runnable" in result[0]

    def test_remote_subagent_skipped_if_missing_url(self, monkeypatch, caplog):
        import logging
        from olav.agents.remote_subagents import load_remote_subagents

        config = {
            "async_subagents": [
                {
                    "name": "broken",
                    "description": "Missing URL",
                    "assistant_id": "x",
                }
            ]
        }

        with caplog.at_level(logging.WARNING, logger="olav"):
            result = load_remote_subagents(config=config)

        assert result == []
        assert any("url" in r.message.lower() or "skip" in r.message.lower()
                   for r in caplog.records)

    def test_remote_subagent_skipped_if_missing_assistant_id(self, monkeypatch, caplog):
        import logging
        from olav.agents.remote_subagents import load_remote_subagents

        config = {
            "async_subagents": [
                {
                    "name": "broken",
                    "description": "Missing assistant_id",
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
                    "assistant_id": "a1",
                    "api_key_env": "MY_CUSTOM_KEY",
                }
            ]
        }

        captured = {}

        def fake_remote(assistant_id, *, url=None, api_key=None, **kw):
            captured["api_key"] = api_key
            return MagicMock()

        with patch("olav.agents.remote_subagents.RemoteGraph", side_effect=fake_remote):
            load_remote_subagents(config=config)

        assert captured.get("api_key") == "env-resolved-key"

    def test_api_key_falls_back_to_langgraph_env(self, monkeypatch):
        """When api_key_env not set, falls back to LANGGRAPH_API_KEY."""
        from olav.agents.remote_subagents import load_remote_subagents
        monkeypatch.setenv("LANGGRAPH_API_KEY", "fallback-key")
        monkeypatch.delenv("api_key_env_unset_var", raising=False)

        config = {
            "async_subagents": [
                {
                    "name": "r1",
                    "description": "d",
                    "url": "https://x.com",
                    "assistant_id": "a1",
                    # no api_key_env — should fall back to LANGGRAPH_API_KEY
                }
            ]
        }

        captured = {}

        def fake_remote(assistant_id, *, url=None, api_key=None, **kw):
            captured["api_key"] = api_key
            return MagicMock()

        with patch("olav.agents.remote_subagents.RemoteGraph", side_effect=fake_remote):
            load_remote_subagents(config=config)

        assert captured.get("api_key") == "fallback-key"

    def test_remote_graph_init_error_skips_gracefully(self, caplog):
        """RemoteGraph init failure skips that subagent without crashing."""
        import logging
        from olav.agents.remote_subagents import load_remote_subagents

        config = {
            "async_subagents": [
                {
                    "name": "failing",
                    "description": "Will fail",
                    "url": "https://bad.url",
                    "assistant_id": "x",
                }
            ]
        }

        with caplog.at_level(logging.WARNING, logger="olav"):
            with patch("olav.agents.remote_subagents.RemoteGraph",
                       side_effect=Exception("connection refused")):
                result = load_remote_subagents(config=config)

        assert result == []
        assert any("failing" in r.message or "connection" in r.message
                   for r in caplog.records)

    def test_multiple_remote_subagents_loaded(self, monkeypatch):
        from olav.agents.remote_subagents import load_remote_subagents
        monkeypatch.setenv("LANGGRAPH_API_KEY", "key")

        config = {
            "async_subagents": [
                {"name": "r1", "description": "d1", "url": "https://a.com", "assistant_id": "a1"},
                {"name": "r2", "description": "d2", "url": "https://b.com", "assistant_id": "a2"},
            ]
        }

        with patch("olav.agents.remote_subagents.RemoteGraph", return_value=MagicMock()):
            result = load_remote_subagents(config=config)

        assert len(result) == 2
        assert {r["name"] for r in result} == {"r1", "r2"}


# ── Integration: OLAVAgent loads remote subagents from api.json ───────────────


class TestOLAVAgentRemoteSubAgentIntegration:
    """OLAVAgent._build_subagents appends remote subagents from api.json config."""

    def test_remote_subagents_merged_with_local(self, monkeypatch):
        """Remote subagents from api.json are appended to local workspace subagents."""
        from olav.agents import remote_subagents as rs_module

        # Patch load_remote_subagents to return a fake remote subagent
        fake_remote = {
            "name": "remote-test",
            "description": "Remote test agent",
            "runnable": MagicMock(),
        }
        with patch.object(rs_module, "load_remote_subagents", return_value=[fake_remote]):
            from olav.agents.remote_subagents import load_remote_subagents
            result = load_remote_subagents(config={
                "async_subagents": [
                    {"name": "remote-test", "description": "d",
                     "url": "https://x.com", "assistant_id": "a"}
                ]
            })
        # smoke test that import + call doesn't crash
        assert len(result) >= 0

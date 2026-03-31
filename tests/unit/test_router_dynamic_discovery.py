"""Tests for §11.5: router dynamic agent discovery (replace hardcoded list)."""

import asyncio
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import pytest


def _make_agent(workspace_root: Path, name: str, route_keywords: list[str] | None = None) -> Path:
    agent_dir = workspace_root / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENT.md").write_text(
        f"---\nname: {name}\ndescription: {name} agent\n---\n# {name}",
        encoding="utf-8",
    )
    manifest = {
        "kind": "Agent",
        "name": name,
        "version": "1.0.0",
        "description": f"{name} agent",
        "route_keywords": route_keywords or [],
    }
    import yaml
    (agent_dir / "MANIFEST.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    return agent_dir


# ── discover_valid_agents ────────────────────────────────────────────────────

class TestDiscoverValidAgents:
    def test_returns_agent_names_from_workspace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_agent(ws_root, "ops")
        _make_agent(ws_root, "config")

        from olav.core.router import discover_valid_agents
        agents = discover_valid_agents()
        assert "ops" in agents
        assert "config" in agents

    def test_includes_default_fallback_when_workspace_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from olav.core.router import discover_valid_agents
        agents = discover_valid_agents()
        # Should always include at least "quick" or "core" as fallback
        assert len(agents) >= 1

    def test_includes_nested_agent_names(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        # Nested: .olav/workspace/netops/ops/MANIFEST.yaml
        nested_dir = ws_root / "netops" / "ops"
        nested_dir.mkdir(parents=True, exist_ok=True)
        import yaml
        (nested_dir / "MANIFEST.yaml").write_text(
            yaml.dump({"kind": "Agent", "name": "ops", "version": "1.0.0",
                       "description": "ops", "route_keywords": []}),
            encoding="utf-8",
        )
        from olav.core.router import discover_valid_agents
        agents = discover_valid_agents()
        assert "ops" in agents

    def test_custom_workspace_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        custom_root = tmp_path / "custom_ws"
        _make_agent(custom_root, "myagent")

        from olav.core.router import discover_valid_agents
        agents = discover_valid_agents(workspace_root=custom_root)
        assert "myagent" in agents


# ── router uses dynamic agents in LLM fallback ───────────────────────────────

class TestRouterFallbackDynamic:
    def test_fallback_validates_against_discovered_agents(self, tmp_path, monkeypatch):
        """Router fallback validates response against workspace-discovered agents."""
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_agent(ws_root, "myagent")
        _make_agent(ws_root, "quick")

        from olav.core.router import SemanticRouter
        router = SemanticRouter()

        # Mock LLM to return "myagent" (a workspace-discovered agent)
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="myagent")
        router._llm = mock_llm

        result = router._fallback_route("do something with myagent")
        assert result["agent"] == "myagent"

    def test_fallback_defaults_when_llm_returns_unknown(self, tmp_path, monkeypatch):
        """Router defaults to 'quick' when LLM returns an unknown agent name."""
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_agent(ws_root, "quick")

        from olav.core.router import SemanticRouter
        router = SemanticRouter()

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="totally_unknown_xyz")
        router._llm = mock_llm

        result = router._fallback_route("some query")
        # Unknown agent → falls back to default
        assert result["agent"] in ("quick", "core", "olav")

    def test_fallback_prompt_mentions_discovered_agents(self, tmp_path, monkeypatch):
        """LLM prompt includes discovered agent names, not hardcoded ones."""
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_agent(ws_root, "infraops", route_keywords=["deploy", "provision"])

        from olav.core.router import SemanticRouter
        router = SemanticRouter()

        captured_prompts = []
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = lambda p: (captured_prompts.append(p), MagicMock(content="infraops"))[1]

        router._llm = mock_llm
        router._fallback_route("deploy new infrastructure")

        assert captured_prompts
        assert "infraops" in captured_prompts[0]

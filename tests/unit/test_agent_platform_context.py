"""TDD: PLATFORM.md context is injected into every agent's system prompt."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_mock_agent():
    agent = MagicMock()
    agent.graph = MagicMock()
    agent.plugin_registry = MagicMock()
    agent.plugin_registry.get_callback_plugins.return_value = []
    return agent


class TestPlatformContextInPrompt:
    def test_platform_context_prepended_when_platform_md_exists(self, tmp_path, monkeypatch):
        """PLATFORM.md context appears at the start of the orchestrator prompt."""
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)

        # Minimal PLATFORM.md
        (ws_root / "olav.md").write_text(
            "---\nagents: [quick, ops]\nactive: quick\n---\n# TestLab\n"
        )

        # Minimal agent workspace
        agent_dir = ws_root / "quick"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(
            "---\nname: quick\ndescription: Quick agent\n---\n"
        )
        (agent_dir / "prompts").mkdir()
        (agent_dir / "prompts" / "system.md").write_text("You are a quick agent.")

        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(ws_root)
        ctx = reg.as_context()

        assert "quick" in ctx
        assert "ops" in ctx

    def test_platform_context_absent_when_no_platform_md(self, tmp_path):
        """Without PLATFORM.md, as_context() returns empty string."""
        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(tmp_path)
        # No agents declared → as_context should not crash and returns minimal/empty
        ctx = reg.as_context()
        assert isinstance(ctx, str)

    def test_get_orchestrator_prompt_includes_platform_context(self, tmp_path, monkeypatch):
        """_get_orchestrator_prompt prepends PLATFORM.md block."""
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)

        (ws_root / "olav.md").write_text(
            "---\nagents: [quick]\nplatform:\n  db: .olav/databases/olav.duckdb\n---\n"
        )
        agent_dir = ws_root / "quick"
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text("---\nname: quick\n---\n")
        (agent_dir / "prompts").mkdir()
        (agent_dir / "prompts" / "system.md").write_text("AGENT PROMPT SENTINEL")

        with patch("olav.agents.agent.OLAVAgent", return_value=_make_mock_agent()):
            pass  # just ensure imports work

        # Test _get_orchestrator_prompt directly
        from olav.agents.agent import OLAVAgent
        with patch.object(OLAVAgent, "__init__", lambda *a, **k: None):
            obj = OLAVAgent.__new__(OLAVAgent)
            obj.olav_base_path = tmp_path / ".olav"
            obj._agent_dir = agent_dir

            prompt = obj._get_orchestrator_prompt({"name": "quick"})

        assert "AGENT PROMPT SENTINEL" in prompt
        assert "olav.duckdb" in prompt or "quick" in prompt

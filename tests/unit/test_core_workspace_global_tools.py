"""Tests for §5: core workspace global tool auto-mount.

OLAVAgent._load_orchestrator_tools() must always load core workspace tools
first (if .olav/workspace/core/SKILL.md exists), then the agent's own tools.
This ensures olav_recall_memory, execute_sql, etc. are available in every agent.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_skill_md(directory: Path, tool_names: list[str]) -> None:
    """Create a minimal SKILL.md and stub tool files in directory."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text("---\nname: test\n---\n", encoding="utf-8")
    tools_dir = directory / "tools"
    tools_dir.mkdir(exist_ok=True)
    for name in tool_names:
        (tools_dir / f"{name}.py").write_text(
            f"from langchain_core.tools import tool\n\n@tool\ndef {name}(x: str) -> str:\n    '''stub'''\n    return x\n",
            encoding="utf-8",
        )


class TestCoreWorkspaceGlobalTools:
    def _make_agent(self, tmp_path: Path, agent_id: str) -> "OLAVAgent":
        """Create a minimal OLAVAgent pointed at tmp_path workspace."""
        from olav.agents.agent import OLAVAgent

        olav_base = tmp_path / ".olav"
        olav_base.mkdir(parents=True, exist_ok=True)

        agent = object.__new__(OLAVAgent)
        agent.agent_id = agent_id
        agent.olav_base_path = olav_base
        agent._agent_dir = olav_base / "workspace" / agent_id
        agent._agent_dir.mkdir(parents=True, exist_ok=True)
        return agent

    def test_core_tools_loaded_when_core_skill_exists(self, tmp_path):
        """core/SKILL.md tools are included in orchestrator tools."""
        agent = self._make_agent(tmp_path, "ops")
        olav_base = tmp_path / ".olav"

        # Create core SKILL.md with one tool
        _make_skill_md(olav_base / "workspace" / "core", ["olav_recall_memory"])
        # Create agent's own SKILL.md with another tool
        _make_skill_md(agent._agent_dir, ["execute_cli"])

        tools = agent._load_orchestrator_tools({})
        tool_names = [t.name for t in tools]

        assert "olav_recall_memory" in tool_names, "core tool olav_recall_memory should be loaded"
        assert "execute_cli" in tool_names, "agent tool execute_cli should also be loaded"

    def test_core_tools_loaded_even_when_agent_has_no_skill_md(self, tmp_path):
        """core tools are still available when agent has no SKILL.md."""
        agent = self._make_agent(tmp_path, "ops")
        olav_base = tmp_path / ".olav"

        _make_skill_md(olav_base / "workspace" / "core", ["olav_recall_memory"])
        # No SKILL.md for ops agent

        tools = agent._load_orchestrator_tools({})
        tool_names = [t.name for t in tools]
        assert "olav_recall_memory" in tool_names

    def test_no_core_tools_when_core_workspace_absent(self, tmp_path):
        """When core workspace doesn't exist, gracefully return agent tools only."""
        agent = self._make_agent(tmp_path, "ops")
        _make_skill_md(agent._agent_dir, ["execute_cli"])

        tools = agent._load_orchestrator_tools({})
        tool_names = [t.name for t in tools]
        assert "execute_cli" in tool_names
        assert "olav_recall_memory" not in tool_names  # core absent

    def test_core_tools_first_agent_tools_second(self, tmp_path):
        """Core tools appear before agent-specific tools in the list."""
        agent = self._make_agent(tmp_path, "ops")
        olav_base = tmp_path / ".olav"

        _make_skill_md(olav_base / "workspace" / "core", ["olav_recall_memory"])
        _make_skill_md(agent._agent_dir, ["execute_cli"])

        tools = agent._load_orchestrator_tools({})
        tool_names = [t.name for t in tools]

        core_idx = tool_names.index("olav_recall_memory")
        agent_idx = tool_names.index("execute_cli")
        assert core_idx < agent_idx, "Core tools should appear before agent tools"

    def test_no_duplicate_tools_when_core_and_agent_overlap(self, tmp_path):
        """If core and agent both declare same tool name, no duplicates."""
        agent = self._make_agent(tmp_path, "ops")
        olav_base = tmp_path / ".olav"

        _make_skill_md(olav_base / "workspace" / "core", ["execute_sql"])
        _make_skill_md(agent._agent_dir, ["execute_sql"])  # same name

        tools = agent._load_orchestrator_tools({})
        tool_names = [t.name for t in tools]
        assert tool_names.count("execute_sql") == 1, "Should deduplicate tools with same name"

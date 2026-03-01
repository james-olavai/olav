"""Smoke tests for OLAV - core module health.

These tests verify the project can at least be imported and configured correctly.
Run with: uv run pytest tests/test_smoke.py -v
"""

from pathlib import Path
import pytest


class TestAgentImports:
    """OLAVAgent module must import cleanly."""

    def test_create_olav_agent_importable(self):
        from olav.agents.agent import OLAVAgent, create_olav_agent

        assert callable(create_olav_agent)
        assert OLAVAgent is not None


class TestWorkspaceStructure:
    """Workspace-based architecture tests."""

    def test_workspace_dir_exists(self, olav_dir):
        workspace = olav_dir / "workspace"
        assert workspace.exists(), "workspace directory must exist"

    def test_all_root_agents_exist(self, olav_dir):
        """All 4 root agents must have AGENT.md."""
        workspace = olav_dir / "workspace"
        for agent_id in ["quick", "ops", "config", "audit"]:
            agent_dir = workspace / agent_id
            assert agent_dir.exists(), f"Agent directory missing: {agent_id}"
            assert (agent_dir / "AGENT.md").exists(), f"AGENT.md missing for: {agent_id}"

    def test_config_agent_has_hitl(self, olav_dir):
        """Config sync subagent must have interrupt_on (HITL) in SKILL.md"""
        import frontmatter

        skill_md = olav_dir / "workspace" / "config" / "sync" / "SKILL.md"
        post = frontmatter.load(str(skill_md))
        
        # Check the subagent has interrupt_on
        assert "interrupt_on" in post.metadata, "config/sync must have interrupt_on (HITL)"

    def test_ops_subagents_exist(self, olav_dir):
        """Ops agent must have subagents: routing-simulator, topology, probe, diff."""
        workspace = olav_dir / "workspace" / "ops"

        expected_subagents = ["routing-simulator", "topology", "probe", "diff"]
        for sa in expected_subagents:
            sa_dir = workspace / sa
            assert sa_dir.exists(), f"Subagent directory missing: ops/{sa}"
            assert (sa_dir / "SKILL.md").exists(), f"SKILL.md missing for: ops/{sa}"


class TestToolDiscovery:
    """Skill tools load without import errors."""

    def test_ops_routing_tools_load(self, olav_dir):
        """Ops/routing-simulator subagent must have tools."""
        from olav.core.tool_discovery import discover_tools

        tools_dir = olav_dir / "workspace" / "ops" / "routing-simulator" / "tools"
        if not tools_dir.exists():
            pytest.skip("tools directory does not exist")

        tools = discover_tools(tools_dir)
        assert len(tools) >= 1, "ops/routing must have at least one tool"

    def test_ops_probe_tools_load(self, olav_dir):
        """Ops/probe subagent must have tools."""
        from olav.core.tool_discovery import discover_tools

        tools_dir = olav_dir / "workspace" / "ops" / "probe" / "tools"
        if not tools_dir.exists():
            pytest.skip("tools directory does not exist")

        tools = discover_tools(tools_dir)
        assert len(tools) >= 1, "ops/probe must have at least one tool"

    def test_config_sync_tools_load(self, olav_dir):
        """Config/sync subagent must have tools."""
        from olav.core.tool_discovery import discover_tools

        tools_dir = olav_dir / "workspace" / "config" / "sync" / "tools"
        if not tools_dir.exists():
            pytest.skip("tools directory does not exist")

        tools = discover_tools(tools_dir)
        assert len(tools) >= 1, "config/sync must have at least one tool"


class TestAgentCreation:
    """Test that agents can be created successfully."""

    @pytest.mark.asyncio
    async def test_quick_agent_creation(self):
        """Quick agent can be created."""
        from olav.agents.agent import OLAVAgent

        agent = OLAVAgent(agent_id="quick", enable_checkpointer=False)
        assert agent.agent_id == "quick"
        await agent.close()

    @pytest.mark.asyncio
    async def test_ops_agent_creation(self):
        """Ops agent can be created."""
        from olav.agents.agent import OLAVAgent

        agent = OLAVAgent(agent_id="ops", enable_checkpointer=False)
        assert agent.agent_id == "ops"
        await agent.close()

    @pytest.mark.asyncio
    async def test_config_agent_creation(self):
        """Config agent can be created."""
        from olav.agents.agent import OLAVAgent

        agent = OLAVAgent(agent_id="config", enable_checkpointer=False)
        assert agent.agent_id == "config"
        await agent.close()

    @pytest.mark.asyncio
    async def test_audit_agent_creation(self):
        """Audit agent can be created."""
        from olav.agents.agent import OLAVAgent

        agent = OLAVAgent(agent_id="audit", enable_checkpointer=False)
        assert agent.agent_id == "audit"
        await agent.close()


@pytest.fixture
def olav_dir():
    return Path(".olav")

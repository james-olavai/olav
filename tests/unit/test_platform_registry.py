"""TDD tests for platform_registry — PLATFORM.md loading and agent discovery.

Three-tier registration model:
  Tier 1 (Global):  PLATFORM.md → declares top-level agents + platform context
  Tier 2 (Agent):   AGENT.md   → declares sub-agents
  Tier 3 (Dynamic): MANIFEST.yaml → skill auto-discovery (unchanged)
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


# ── Tier 1: PlatformRegistry ─────────────────────────────────────────────────


class TestPlatformRegistryLoad:
    def test_load_returns_agent_list(self, tmp_path):
        """PLATFORM.md frontmatter agents: list is returned."""
        platform_md = tmp_path / "olav.md"
        platform_md.write_text(textwrap.dedent("""\
            ---
            agents:
              - quick
              - ops
              - config
              - core
            active: quick
            ---
            # My Platform
        """))
        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(tmp_path)
        assert reg.agents == ["quick", "ops", "config", "core"]

    def test_load_returns_active_agent(self, tmp_path):
        platform_md = tmp_path / "olav.md"
        platform_md.write_text("---\nagents: [quick, ops]\nactive: ops\n---\n")
        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(tmp_path)
        assert reg.active == "ops"

    def test_load_returns_platform_context(self, tmp_path):
        """platform: block is parsed into a dict."""
        platform_md = tmp_path / "olav.md"
        platform_md.write_text(textwrap.dedent("""\
            ---
            agents: [quick]
            platform:
              db: .olav/databases/olav.duckdb
              services:
                clab: http://192.168.100.12:8080
            ---
        """))
        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(tmp_path)
        assert reg.platform["db"] == ".olav/databases/olav.duckdb"
        assert reg.platform["services"]["clab"] == "http://192.168.100.12:8080"

    def test_load_missing_file_returns_empty_defaults(self, tmp_path):
        """When PLATFORM.md doesn't exist, returns empty/default registry."""
        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(tmp_path)
        assert reg.agents == []
        assert reg.active is None
        assert reg.platform == {}

    def test_load_invalid_yaml_returns_empty_defaults(self, tmp_path):
        """Malformed PLATFORM.md doesn't crash — graceful fallback."""
        platform_md = tmp_path / "olav.md"
        platform_md.write_text("---\n: : invalid yaml\n---\n")
        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(tmp_path)
        assert isinstance(reg.agents, list)

    def test_load_no_frontmatter_returns_defaults(self, tmp_path):
        """Plain markdown without frontmatter returns defaults."""
        platform_md = tmp_path / "olav.md"
        platform_md.write_text("# Just a heading\n\nNo frontmatter here.\n")
        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(tmp_path)
        assert reg.agents == []

    def test_load_body_text_accessible(self, tmp_path):
        """The markdown body (description) is accessible for context injection."""
        platform_md = tmp_path / "olav.md"
        platform_md.write_text(textwrap.dedent("""\
            ---
            agents: [quick]
            ---
            # Lab Platform
            Deployed in home lab, SRL nodes.
        """))
        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(tmp_path)
        assert "Lab Platform" in reg.description or "Lab Platform" in reg.body


class TestPlatformRegistryContextString:
    def test_as_context_includes_agents(self, tmp_path):
        """as_context() returns a string mentioning the registered agents."""
        platform_md = tmp_path / "olav.md"
        platform_md.write_text("---\nagents: [quick, ops, core]\nactive: quick\n---\n")
        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(tmp_path)
        ctx = reg.as_context()
        assert "quick" in ctx
        assert "ops" in ctx

    def test_as_context_includes_platform_services(self, tmp_path):
        platform_md = tmp_path / "olav.md"
        platform_md.write_text(textwrap.dedent("""\
            ---
            agents: [quick]
            platform:
              services:
                clab: http://192.168.100.12:8080
            ---
        """))
        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(tmp_path)
        ctx = reg.as_context()
        assert "clab" in ctx or "192.168.100.12" in ctx


# ── discover_valid_agents: reads PLATFORM.md first ───────────────────────────


class TestDiscoverValidAgents:
    def test_reads_agents_from_platform_md(self, tmp_path, monkeypatch):
        """discover_valid_agents uses PLATFORM.md agents list."""
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)
        (ws_root / "olav.md").write_text(
            "---\nagents: [quick, ops, audit]\nactive: quick\n---\n"
        )
        monkeypatch.chdir(tmp_path)
        from olav.core import router as _router
        import importlib; importlib.reload(_router)
        from olav.core.router import discover_valid_agents
        agents = discover_valid_agents(ws_root)
        assert agents == ["quick", "ops", "audit"]

    def test_fallback_to_directory_scan_when_no_platform_md(self, tmp_path, monkeypatch):
        """Without PLATFORM.md, falls back to scanning AGENT.md directories."""
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)
        # Create agent dirs with AGENT.md (no PLATFORM.md, no MANIFEST.yaml)
        for name in ["quick", "ops"]:
            d = ws_root / name
            d.mkdir()
            (d / "AGENT.md").write_text(f"---\nname: {name}\n---\n")
        monkeypatch.chdir(tmp_path)
        from olav.core.router import discover_valid_agents
        agents = discover_valid_agents(ws_root)
        assert "quick" in agents
        assert "ops" in agents

    def test_fallback_to_core_when_workspace_empty(self, tmp_path, monkeypatch):
        """Returns ['core'] if workspace is empty and no PLATFORM.md (v0.15+)."""
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        from olav.core.router import discover_valid_agents
        agents = discover_valid_agents(ws_root)
        assert agents == ["core"]

    def test_platform_md_takes_precedence_over_manifest_scan(self, tmp_path, monkeypatch):
        """PLATFORM.md agents list wins over MANIFEST.yaml discovery."""
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)
        # PLATFORM.md declares only [quick]
        (ws_root / "olav.md").write_text("---\nagents: [quick]\n---\n")
        # But there's a MANIFEST.yaml for "ops" — should be ignored for Tier 1
        ops_dir = ws_root / "ops"
        ops_dir.mkdir()
        (ops_dir / "MANIFEST.yaml").write_text(
            "kind: Agent\nname: ops\nversion: '1.0'\nroute_keywords: [ops]\n"
        )
        monkeypatch.chdir(tmp_path)
        from olav.core.router import discover_valid_agents
        agents = discover_valid_agents(ws_root)
        assert agents == ["quick"]
        assert "ops" not in agents


# ── Agent-level: AGENT.md sub-agent registration unchanged ───────────────────


class TestAgentMdSubagentRegistration:
    def test_agent_md_subagents_field_is_respected(self, tmp_path):
        """AGENT.md subagents: list is used as-is for sub-agent construction."""
        import yaml
        agent_dir = tmp_path / "quick"
        agent_dir.mkdir()
        config = {
            "name": "quick",
            "subagents": ["probe/SKILL.md", "diff/SKILL.md"],
        }
        (agent_dir / "AGENT.md").write_text(
            "---\n" + yaml.dump(config) + "---\n"
        )
        import frontmatter
        post = frontmatter.load(str(agent_dir / "AGENT.md"))
        assert post.metadata["subagents"] == ["probe/SKILL.md", "diff/SKILL.md"]


# ── Skill tier: MANIFEST.yaml only injects Skills, not Agents ────────────────


class TestManifestOnlyInjectsSkills:
    def test_agent_kind_manifest_not_injected_as_subagent(self, tmp_path):
        """MANIFEST.yaml with kind: Agent is NOT injected via merge_into_config."""
        from pathlib import Path
        import yaml
        manifest_path = tmp_path / "MANIFEST.yaml"
        manifest_path.write_text(yaml.dump({
            "kind": "Agent",
            "name": "myagent",
            "version": "1.0",
            "agent": "quick",
            "route_keywords": ["myagent"],
        }))
        from olav.core.agent_registry import AgentManifest, merge_into_config
        m = AgentManifest.from_yaml(manifest_path)
        config = {"name": "quick", "subagents": []}
        result = merge_into_config(config, {"myagent": m}, "quick")
        # kind: Agent must NOT be injected
        assert result.get("subagents", []) == []

    def test_skill_kind_manifest_is_injected_when_skill_md_exists(self, tmp_path):
        """MANIFEST.yaml with kind: Skill and SKILL.md present IS injected."""
        import yaml
        skill_dir = tmp_path / "probe"
        skill_dir.mkdir()
        (skill_dir / "MANIFEST.yaml").write_text(yaml.dump({
            "kind": "Skill",
            "name": "probe",
            "version": "1.0",
            "agent": "quick",
            "route_keywords": ["probe"],
        }))
        (skill_dir / "SKILL.md").write_text("---\nname: probe\ntools: []\n---\n")

        from olav.core.agent_registry import AgentManifest, merge_into_config
        m = AgentManifest.from_yaml(skill_dir / "MANIFEST.yaml")
        config = {"name": "quick", "subagents": []}
        result = merge_into_config(config, {"probe": m}, "quick")
        assert len(result.get("subagents", [])) == 1

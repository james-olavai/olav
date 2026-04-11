"""tests/unit/test_refresh_command.py — TDD for olav refresh command.

Tests for:
- _parse_agent_frontmatter: parse YAML frontmatter from AGENT.md
- _scan_agents: find all agents with AGENT.md in workspace
- _write_platform_md: rebuild PLATFORM.md from agent list
- _update_main_agent_routing: replace routing section in system.md
- refresh_workspace: orchestrate the full refresh

Rev 93 / ISSUE-P2-NO-GLOBAL-AGENT-REGISTRY
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from olav.cli.commands.refresh import (
    _ROUTING_END_MARKER,
    _ROUTING_START_MARKER,
    _parse_agent_frontmatter,
    _scan_agents,
    _update_main_agent_routing,
    _write_platform_md,
    refresh_workspace,
)


# ── fixtures ────────────────────────────────────────────────────────────────


def _make_agent(parent_dir: Path, name: str, meta: dict | None = None) -> Path:
    """Write an AGENT.md file in parent_dir/<name>/ and return the dir."""
    agent_dir = parent_dir / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    if meta is None:
        meta = {
            "name": f"{name}-agent",
            "description": f"The {name} agent.",
        }
    frontmatter = yaml.dump(meta, default_flow_style=False)
    (agent_dir / "AGENT.md").write_text(f"---\n{frontmatter}---\n\n# {name}\n", encoding="utf-8")
    return agent_dir


def _make_system_md(olav_dir: Path, with_markers: bool = True) -> Path:
    """Write a minimal system.md with or without routing markers."""
    prompts_dir = olav_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    if with_markers:
        content = (
            "You are OLAV.\n\n"
            "- Help you decide:\n"
            f"{_ROUTING_START_MARKER}\n"
            "  - `old` — Old description\n"
            f"{_ROUTING_END_MARKER}\n\n"
            "More text here.\n"
        )
    else:
        content = "You are OLAV.\n\n- Help you decide:\n  - `old` — old\n\nMore text.\n"
    system_md = prompts_dir / "system.md"
    system_md.write_text(content, encoding="utf-8")
    return system_md


# ── _parse_agent_frontmatter ────────────────────────────────────────────────


class TestParseAgentFrontmatter:
    def test_reads_name_and_description(self, tmp_path):
        agent_md = tmp_path / "AGENT.md"
        agent_md.write_text(
            '---\nname: quick-orchestrator\ndescription: "Quick Query Agent"\n---\n\n# Quick\n',
            encoding="utf-8",
        )
        meta = _parse_agent_frontmatter(agent_md)
        assert meta["name"] == "quick-orchestrator"
        assert meta["description"] == "Quick Query Agent"

    def test_returns_empty_dict_if_no_frontmatter(self, tmp_path):
        agent_md = tmp_path / "AGENT.md"
        agent_md.write_text("# Just a heading\n", encoding="utf-8")
        assert _parse_agent_frontmatter(agent_md) == {}

    def test_returns_empty_dict_if_file_missing(self, tmp_path):
        assert _parse_agent_frontmatter(tmp_path / "nonexistent.md") == {}

    def test_tolerates_malformed_yaml(self, tmp_path):
        agent_md = tmp_path / "AGENT.md"
        agent_md.write_text("---\nname: [bad: yaml\n---\n", encoding="utf-8")
        result = _parse_agent_frontmatter(agent_md)
        assert result == {}


# ── _scan_agents ────────────────────────────────────────────────────────────


class TestScanAgents:
    def test_finds_all_agents_with_agent_md(self, tmp_path):
        ws = tmp_path / "workspace"
        _make_agent(ws, "quick", {"name": "quick-orchestrator", "description": "Fast"})
        _make_agent(ws, "ops", {"name": "ops-orchestrator", "description": "Deep"})
        # Directory without AGENT.md — must be skipped
        (ws / "no-agent").mkdir()
        (ws / "no-agent" / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")

        agents = _scan_agents(ws)
        flags = [a["flag"] for a in agents]
        assert "quick" in flags
        assert "ops" in flags
        assert "no-agent" not in flags
        assert len(agents) == 2

    def test_returns_empty_for_empty_workspace(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        assert _scan_agents(ws) == []

    def test_agent_dict_has_required_keys(self, tmp_path):
        ws = tmp_path / "workspace"
        _make_agent(ws, "config", {"name": "config-orch", "description": "Config agent."})
        agents = _scan_agents(ws)
        assert len(agents) == 1
        a = agents[0]
        assert a["flag"] == "config"
        assert a["name"] == "config-orch"
        assert a["description"] == "Config agent."

    def test_sorted_by_flag_name(self, tmp_path):
        ws = tmp_path / "workspace"
        _make_agent(ws, "zzz", {"name": "zzz", "description": ""})
        _make_agent(ws, "aaa", {"name": "aaa", "description": ""})
        _make_agent(ws, "mmm", {"name": "mmm", "description": ""})
        agents = _scan_agents(ws)
        flags = [a["flag"] for a in agents]
        assert flags == sorted(flags)


# ── _write_platform_md ──────────────────────────────────────────────────────


class TestWritePlatformMd:
    def test_creates_new_platform_md(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        agents = [
            {"flag": "quick", "name": "quick-orchestrator", "description": "Fast SQL", "kind": ""},
            {"flag": "ops", "name": "ops-orchestrator", "description": "Deep troubleshooting", "kind": ""},
        ]
        _write_platform_md(ws, agents)
        platform_md = ws / "PLATFORM.md"
        assert platform_md.exists()

    def test_frontmatter_contains_agents_list(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        agents = [
            {"flag": "quick", "name": "quick-orchestrator", "description": "Fast", "kind": ""},
            {"flag": "ops", "name": "ops-orch", "description": "Deep", "kind": ""},
        ]
        _write_platform_md(ws, agents)
        text = (ws / "PLATFORM.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        assert meta["agents"] == ["quick", "ops"]

    def test_preserves_existing_active_agent(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        # Write an existing PLATFORM.md with active=ops
        (ws / "PLATFORM.md").write_text(
            "---\nactive: ops\nagents:\n- ops\n---\n# Old\n",
            encoding="utf-8",
        )
        agents = [
            {"flag": "quick", "name": "quick-orch", "description": "", "kind": ""},
            {"flag": "ops", "name": "ops-orch", "description": "", "kind": ""},
        ]
        _write_platform_md(ws, agents)
        text = (ws / "PLATFORM.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        assert meta["active"] == "ops"

    def test_preserves_existing_platform_section(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "PLATFORM.md").write_text(
            "---\nactive: quick\nagents: [quick]\nplatform:\n  db: .olav/databases/main.duckdb\n---\n",
            encoding="utf-8",
        )
        agents = [{"flag": "quick", "name": "quick-orch", "description": "", "kind": ""}]
        _write_platform_md(ws, agents)
        text = (ws / "PLATFORM.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        assert meta["platform"]["db"] == ".olav/databases/main.duckdb"

    def test_body_contains_agent_table(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        agents = [
            {"flag": "quick", "name": "quick-orch", "description": "Fast lookup", "kind": ""},
        ]
        _write_platform_md(ws, agents)
        body = (ws / "PLATFORM.md").read_text(encoding="utf-8")
        assert "quick" in body
        assert "Fast lookup" in body


# ── _update_main_agent_routing ──────────────────────────────────────────────


class TestUpdateMainAgentRouting:
    def test_replaces_routing_section(self, tmp_path):
        ws = tmp_path / "workspace"
        olav_dir = _make_agent(ws, "olav", {"name": "olav-main", "description": ""})
        system_md = _make_system_md(olav_dir, with_markers=True)

        agents = [
            {"flag": "quick", "name": "quick-orch", "description": "Quick Query Agent — Fast SQL", "kind": ""},
            {"flag": "ops", "name": "ops-orch", "description": "Operations Agent — Deep troubleshooting", "kind": ""},
            {"flag": "olav", "name": "olav-main", "description": "Main agent", "kind": ""},
        ]
        result = _update_main_agent_routing(ws, agents)
        assert result is True

        text = system_md.read_text(encoding="utf-8")
        # olav should be excluded from routing table
        assert "`olav`" not in text.split(_ROUTING_START_MARKER)[1].split(_ROUTING_END_MARKER)[0]
        assert "`quick`" in text
        assert "`ops`" in text
        # old content replaced
        assert "`old`" not in text

    def test_returns_false_when_markers_missing(self, tmp_path):
        ws = tmp_path / "workspace"
        olav_dir = _make_agent(ws, "olav", {"name": "olav-main", "description": ""})
        _make_system_md(olav_dir, with_markers=False)
        result = _update_main_agent_routing(ws, [])
        assert result is False

    def test_returns_false_when_system_md_missing(self, tmp_path):
        ws = tmp_path / "workspace"
        result = _update_main_agent_routing(ws, [])
        assert result is False

    def test_preserves_text_outside_markers(self, tmp_path):
        ws = tmp_path / "workspace"
        olav_dir = _make_agent(ws, "olav", {"name": "olav-main", "description": ""})
        system_md = _make_system_md(olav_dir, with_markers=True)

        agents = [{"flag": "quick", "name": "quick-orch", "description": "Quick Agent — SQL lookups", "kind": ""}]
        _update_main_agent_routing(ws, agents)

        text = system_md.read_text(encoding="utf-8")
        assert "You are OLAV." in text
        assert "More text here." in text


# ── refresh_workspace ────────────────────────────────────────────────────────


class TestRefreshWorkspace:
    def _build_workspace(self, tmp_path: Path) -> Path:
        """Build a minimal workspace with quick + ops + olav agents."""
        ws = tmp_path / "workspace"
        _make_agent(ws, "quick", {"name": "quick-orchestrator", "description": "Quick Agent — Fast SQL lookup"})
        _make_agent(ws, "ops", {"name": "ops-orchestrator", "description": "Operations Agent — Deep troubleshooting"})
        olav_dir = _make_agent(ws, "olav", {"name": "olav-main", "description": "Main OLAV Agent"})
        _make_system_md(olav_dir, with_markers=True)
        return ws

    def test_returns_success_message(self, tmp_path):
        ws = self._build_workspace(tmp_path)
        result = refresh_workspace(ws)
        assert "✓" in result
        assert "3 agents" in result

    def test_creates_platform_md(self, tmp_path):
        ws = self._build_workspace(tmp_path)
        refresh_workspace(ws)
        assert (ws / "PLATFORM.md").exists()

    def test_platform_md_lists_all_agents(self, tmp_path):
        ws = self._build_workspace(tmp_path)
        refresh_workspace(ws)
        text = (ws / "PLATFORM.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        assert set(meta["agents"]) == {"quick", "ops", "olav"}

    def test_routing_table_updated_in_system_md(self, tmp_path):
        ws = self._build_workspace(tmp_path)
        refresh_workspace(ws)
        system_md = ws / "olav" / "prompts" / "system.md"
        text = system_md.read_text(encoding="utf-8")
        assert "`quick`" in text
        assert "`ops`" in text

    def test_error_when_workspace_missing(self, tmp_path):
        result = refresh_workspace(tmp_path / "nonexistent")
        assert result.startswith("error:")

    def test_warning_when_no_agents(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = refresh_workspace(ws)
        assert "warning:" in result

    def test_idempotent_second_run(self, tmp_path):
        ws = self._build_workspace(tmp_path)
        r1 = refresh_workspace(ws)
        r2 = refresh_workspace(ws)
        assert "✓" in r1
        assert "✓" in r2
        # Same agents both times
        text = (ws / "PLATFORM.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        assert set(meta["agents"]) == {"quick", "ops", "olav"}

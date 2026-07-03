"""tests/unit/test_refresh_command.py — TDD for olav refresh command.

Tests for:
- _parse_agent_frontmatter: parse YAML frontmatter from AGENT.md
- _scan_agents: find all agents with SKILL.md/AGENT.md in workspace
- _write_platform_md: rebuild olav.md from agent list
- refresh_workspace: orchestrate the full refresh

Rev 93 / ISSUE-P2-NO-GLOBAL-AGENT-REGISTRY. The system.md routing-table
half of refresh (``_update_main_agent_routing``) was removed 2026-07-02 —
it targeted ``<workspace>/core/prompts/system.md``, a file that never
existed under the post-SKILL.md-migration workspace layout, so the
function always no-op'd (dev_docs/99 §3.6).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from olav.cli.commands.refresh import (
    _parse_agent_frontmatter,
    _scan_agents,
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
        # Directory with neither SKILL.md nor AGENT.md — must be skipped
        (ws / "no-agent").mkdir()
        (ws / "no-agent" / "README.md").write_text("not an agent file", encoding="utf-8")

        agents = _scan_agents(ws)
        flags = [a["flag"] for a in agents]
        assert "quick" in flags
        assert "ops" in flags
        assert "no-agent" not in flags
        assert len(agents) == 2

    def test_prefers_skill_md_over_agent_md(self, tmp_path):
        """SKILL.md is preferred (post-ADR-0008 merge); a directory with
        only SKILL.md (no AGENT.md) must still be found, not skipped."""
        ws = tmp_path / "workspace"
        skill_dir = ws / "modern"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            '---\nname: modern-agent\ndescription: "SKILL.md-only agent"\n---\n',
            encoding="utf-8",
        )

        agents = _scan_agents(ws)
        flags = [a["flag"] for a in agents]
        assert "modern" in flags
        assert len(agents) == 1

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
        platform_md = ws / "olav.md"
        assert platform_md.exists()

    def test_frontmatter_contains_agents_list(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        agents = [
            {"flag": "quick", "name": "quick-orchestrator", "description": "Fast", "kind": ""},
            {"flag": "ops", "name": "ops-orch", "description": "Deep", "kind": ""},
        ]
        _write_platform_md(ws, agents)
        text = (ws / "olav.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        assert meta["agents"] == ["quick", "ops"]

    def test_preserves_existing_active_agent(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        # Write an existing olav.md with active=ops
        (ws / "olav.md").write_text(
            "---\nactive: ops\nagents:\n- ops\n---\n# Old\n",
            encoding="utf-8",
        )
        agents = [
            {"flag": "quick", "name": "quick-orch", "description": "", "kind": ""},
            {"flag": "ops", "name": "ops-orch", "description": "", "kind": ""},
        ]
        _write_platform_md(ws, agents)
        text = (ws / "olav.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        assert meta["active"] == "ops"

    def test_preserves_existing_platform_section(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "olav.md").write_text(
            "---\nactive: quick\nagents: [quick]\nplatform:\n  db: .olav/databases/main.duckdb\n---\n",
            encoding="utf-8",
        )
        agents = [{"flag": "quick", "name": "quick-orch", "description": "", "kind": ""}]
        _write_platform_md(ws, agents)
        text = (ws / "olav.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        assert meta["platform"]["db"] == ".olav/databases/main.duckdb"

    def test_body_contains_agent_table(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        agents = [
            {"flag": "quick", "name": "quick-orch", "description": "Fast lookup", "kind": ""},
        ]
        _write_platform_md(ws, agents)
        body = (ws / "olav.md").read_text(encoding="utf-8")
        assert "quick" in body
        assert "Fast lookup" in body


# ── refresh_workspace ────────────────────────────────────────────────────────


class TestRefreshWorkspace:
    def _build_workspace(self, tmp_path: Path) -> Path:
        """Build a minimal workspace with quick + ops + olav agents."""
        ws = tmp_path / "workspace"
        _make_agent(ws, "quick", {"name": "quick-orchestrator", "description": "Quick Agent — Fast SQL lookup"})
        _make_agent(ws, "ops", {"name": "ops-orchestrator", "description": "Operations Agent — Deep troubleshooting"})
        _make_agent(ws, "olav", {"name": "olav-main", "description": "Main OLAV Agent"})
        return ws

    def test_returns_success_message(self, tmp_path):
        ws = self._build_workspace(tmp_path)
        result = refresh_workspace(ws)
        assert "✓" in result
        assert "3 agents" in result

    def test_creates_platform_md(self, tmp_path):
        ws = self._build_workspace(tmp_path)
        refresh_workspace(ws)
        assert (ws / "olav.md").exists()

    def test_platform_md_lists_all_agents(self, tmp_path):
        ws = self._build_workspace(tmp_path)
        refresh_workspace(ws)
        text = (ws / "olav.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        assert set(meta["agents"]) == {"quick", "ops", "olav"}

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
        text = (ws / "olav.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(text.split("---", 2)[1])
        assert set(meta["agents"]) == {"quick", "ops", "olav"}

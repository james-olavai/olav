"""
tests/unit/test_agent_registry.py
──────────────────────────────────
TDD guard for src/olav/core/agent_registry.py

Tests verify:
  1. AgentManifest is importable and holds expected attributes
  2. discover_agents() returns {} for non-existent workspace
  3. discover_agents() returns {} when no MANIFEST.yaml files present
  4. discover_agents() reads a single MANIFEST.yaml and indexes by name
  5. discover_agents() reads Agent kind with route_keywords + tools_dir
  6. discover_agents() reads Skill kind with agent linkage
  7. discover_agents() silently ignores malformed YAML
  8. discover_agents() scans recursively (nested MANIFEST.yaml files)
  9. AgentManifest.from_yaml() populates version, kind, requires
 10. discover_agents() with multiple manifests returns all in dict
"""

import pytest
import tempfile
from pathlib import Path


# ── 1. importable ─────────────────────────────────────────────────────────────


def test_agent_registry_importable():
    from olav.core.agent_registry import AgentManifest, discover_agents


def test_agent_manifest_has_required_fields():
    from olav.core.agent_registry import AgentManifest

    m = AgentManifest(
        name="ops",
        kind="Agent",
        version="0.11.0",
        path=Path("/fake/MANIFEST.yaml"),
    )
    assert m.name == "ops"
    assert m.kind == "Agent"
    assert m.version == "0.11.0"
    assert m.path == Path("/fake/MANIFEST.yaml")
    assert m.route_keywords == []
    assert m.tools_dir is None
    assert m.agent is None
    assert m.requires == []


# ── 2. missing workspace ───────────────────────────────────────────────────────


def test_discover_agents_missing_workspace_returns_empty():
    from olav.core.agent_registry import discover_agents

    result = discover_agents(Path("/nonexistent/workspace/xyz"))
    assert result == {}


# ── 3. no MANIFEST.yaml files ─────────────────────────────────────────────────


def test_discover_agents_no_manifests_returns_empty(tmp_path):
    from olav.core.agent_registry import discover_agents

    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "AGENT.md").write_text("# ops")
    result = discover_agents(tmp_path)
    assert result == {}


# ── 4. single skill manifest ──────────────────────────────────────────────────


def test_discover_agents_reads_single_manifest(tmp_path):
    from olav.core.agent_registry import discover_agents

    manifest_dir = tmp_path / "sync"
    manifest_dir.mkdir()
    (manifest_dir / "MANIFEST.yaml").write_text("""\
kind: Skill
name: sync
version: "0.11.0"
agent: config
""")
    result = discover_agents(tmp_path)
    assert "sync" in result
    assert result["sync"].kind == "Skill"
    assert result["sync"].version == "0.11.0"


# ── 5. agent kind with route_keywords + tools_dir ─────────────────────────────


def test_discover_agents_reads_agent_kind(tmp_path):
    from olav.core.agent_registry import discover_agents

    manifest_dir = tmp_path / "ops"
    manifest_dir.mkdir()
    (manifest_dir / "MANIFEST.yaml").write_text("""\
kind: Agent
name: ops
version: "0.11.0"
route_keywords:
  - troubleshoot
  - probe
  - diff config
tools_dir: tools/
""")
    result = discover_agents(tmp_path)
    m = result["ops"]
    assert m.kind == "Agent"
    assert "troubleshoot" in m.route_keywords
    assert "probe" in m.route_keywords
    assert m.tools_dir == "tools/"
    assert m.agent is None


# ── 6. skill kind with agent linkage ──────────────────────────────────────────


def test_discover_agents_reads_skill_agent_linkage(tmp_path):
    from olav.core.agent_registry import discover_agents

    (tmp_path / "discovery").mkdir()
    (tmp_path / "discovery" / "MANIFEST.yaml").write_text("""\
kind: Skill
name: discovery
version: "0.11.0"
agent: config
route_keywords:
  - classify field
  - discover schema
requires:
  - olav-platform>=0.11
""")
    result = discover_agents(tmp_path)
    m = result["discovery"]
    assert m.agent == "config"
    assert "classify field" in m.route_keywords
    assert "olav-platform>=0.11" in m.requires


# ── 7. malformed YAML is silently ignored ─────────────────────────────────────


def test_discover_agents_ignores_malformed_yaml(tmp_path):
    from olav.core.agent_registry import discover_agents

    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "MANIFEST.yaml").write_text(": bad: yaml: {[[[ }\n")
    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "MANIFEST.yaml").write_text("""\
kind: Agent
name: good
version: "1.0.0"
""")
    result = discover_agents(tmp_path)
    assert "bad" not in result
    assert "good" in result


# ── 8. recursive scan ─────────────────────────────────────────────────────────


def test_discover_agents_scans_recursively(tmp_path):
    from olav.core.agent_registry import discover_agents

    nested = tmp_path / "config" / "sync"
    nested.mkdir(parents=True)
    (nested / "MANIFEST.yaml").write_text("""\
kind: Skill
name: sync
version: "0.11.0"
agent: config
""")
    result = discover_agents(tmp_path)
    assert "sync" in result


# ── 9. from_yaml populates version, kind, requires ────────────────────────────


def test_from_yaml_full_fields(tmp_path):
    from olav.core.agent_registry import AgentManifest

    p = tmp_path / "MANIFEST.yaml"
    p.write_text("""\
kind: Agent
name: audit
version: "0.12.0"
route_keywords:
  - audit
  - compliance
requires:
  - olav-platform>=0.11
  - duckdb>=1.0
tools_dir: tools/
""")
    m = AgentManifest.from_yaml(p)
    assert m.name == "audit"
    assert m.kind == "Agent"
    assert m.version == "0.12.0"
    assert m.route_keywords == ["audit", "compliance"]
    assert "duckdb>=1.0" in m.requires
    assert m.tools_dir == "tools/"
    assert m.path == p


# ── 10. multiple manifests ────────────────────────────────────────────────────


def test_discover_agents_multiple_manifests(tmp_path):
    from olav.core.agent_registry import discover_agents

    for name, kind in [("ops", "Agent"), ("audit", "Agent"), ("sync", "Skill")]:
        d = tmp_path / name
        d.mkdir()
        (d / "MANIFEST.yaml").write_text(f'kind: {kind}\nname: {name}\nversion: "0.11.0"\n')
    result = discover_agents(tmp_path)
    assert set(result.keys()) == {"ops", "audit", "sync"}
    assert result["ops"].kind == "Agent"
    assert result["sync"].kind == "Skill"


# ── 11. merge_into_config dependency gating (HP-3) ───────────────────────────


def test_merge_into_config_skips_unavailable_deps(tmp_path):
    from olav.core.agent_registry import AgentManifest, merge_into_config

    skill_dir = tmp_path / "broken_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# broken\n")
    manifest = AgentManifest(
        name="broken_skill",
        kind="Skill",
        version="0.1.0",
        path=skill_dir / "MANIFEST.yaml",
        agent="quick",
        required_modules=["nonexistent_xyz"],
    )
    manifests = {"broken_skill": manifest}
    config: dict = {"subagents": []}
    result = merge_into_config(config, manifests, "quick")
    assert "broken_skill/SKILL.md" not in (result.get("subagents") or [])


def test_merge_into_config_injects_available_deps(tmp_path):
    from olav.core.agent_registry import AgentManifest, merge_into_config

    skill_dir = tmp_path / "good_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# good\n")
    manifest = AgentManifest(
        name="good_skill",
        kind="Skill",
        version="0.1.0",
        path=skill_dir / "MANIFEST.yaml",
        agent="quick",
        required_modules=["os", "sys"],
    )
    manifests = {"good_skill": manifest}
    config: dict = {"subagents": []}
    result = merge_into_config(config, manifests, "quick")
    assert "good_skill/SKILL.md" in (result.get("subagents") or [])


def test_merge_into_config_logs_unavailable_warning(tmp_path, caplog):
    import logging
    from olav.core.agent_registry import AgentManifest, merge_into_config

    skill_dir = tmp_path / "missing_dep"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# missing\n")
    manifest = AgentManifest(
        name="missing_dep",
        kind="Skill",
        version="0.1.0",
        path=skill_dir / "MANIFEST.yaml",
        agent="quick",
        required_modules=["nonexistent_xyz"],
    )
    manifests = {"missing_dep": manifest}
    config: dict = {"subagents": []}
    with caplog.at_level(logging.WARNING, logger="olav.core.agent_registry"):
        merge_into_config(config, manifests, "quick")
    assert any("unavailable" in r.message for r in caplog.records)

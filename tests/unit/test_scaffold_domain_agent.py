"""
tests/unit/test_scaffold_domain_agent.py
─────────────────────────────────────────
TDD guard for ``olav.core.curator.scaffold_domain_agent``.

The canonical home for schema-discovery / scaffolding tooling migrated:

* ARCH-20 Phase 1: ``config/discovery`` → ``audit/learner`` (workspace MCP)
* R91 (ADR-0007): ``audit/curator/tools/scaffold_domain_agent.py`` →
  ``olav.core.curator.scaffold_domain_agent`` (Python helper)
* R92.3 (ADR-0008): also exposed as a skill script at
  ``audit/curator/scripts/scaffold_domain_agent.py`` invoked via
  ``execute_skill_script``

Tests target the Python helper (the source of truth); skill-script
invocation is exercised separately in ``test_skill_runner.py``.

Tests verify:
  1. scaffold_domain_agent is importable
  2. Creates MANIFEST.yaml with correct fields for Agent kind
  3. Creates AGENT.md stub for Agent kind
  4. Creates SKILL.md stub for Skill kind, no AGENT.md
  5. Creates tools/ directory when create_tools_dir=True
  6. Returns dict with 'created_files', 'workspace_dir', 'name' keys
  7. Raises ValueError for unknown kind
  8. Idempotent: does not overwrite existing files by default
  9. overwrite=True replaces existing MANIFEST.yaml
 10. discover_agents can find the scaffolded MANIFEST.yaml
"""

import pytest
import yaml
from pathlib import Path


def _load_scaffold():
    """Load scaffold_domain_agent — now via olav.core.curator (R91)."""
    import olav.core.curator as mod
    return mod


# ── 1. importable ─────────────────────────────────────────────────────────────

def test_scaffold_domain_agent_importable():
    mod = _load_scaffold()
    assert hasattr(mod, "scaffold_domain_agent")


# ── 2. creates MANIFEST.yaml for Agent kind ───────────────────────────────────

def test_scaffold_creates_manifest_agent(tmp_path):
    scaffold_domain_agent = _load_scaffold().scaffold_domain_agent
    result = scaffold_domain_agent(
        name="itsm",
        kind="Agent",
        description="IT Service Management agent",
        route_keywords=["create ticket", "list incidents", "resolve issue"],
        workspace_root=tmp_path,
    )
    manifest_path = tmp_path / "itsm" / "MANIFEST.yaml"
    assert manifest_path.exists(), "MANIFEST.yaml must be created"
    data = yaml.safe_load(manifest_path.read_text())
    assert data["kind"] == "Agent"
    assert data["name"] == "itsm"
    assert "create ticket" in data["route_keywords"]
    assert data["version"] == "0.11.0"


# ── 3. creates AGENT.md for Agent kind ────────────────────────────────────────

def test_scaffold_creates_agent_md(tmp_path):
    scaffold_domain_agent = _load_scaffold().scaffold_domain_agent
    scaffold_domain_agent(
        name="netops",
        kind="Agent",
        description="Network operations automation",
        route_keywords=["check interface"],
        workspace_root=tmp_path,
    )
    agent_md = tmp_path / "netops" / "AGENT.md"
    assert agent_md.exists(), "AGENT.md must be created for Agent kind"
    content = agent_md.read_text()
    assert "netops" in content
    assert "Network operations automation" in content


# ── 4. creates SKILL.md for Skill kind, no AGENT.md ──────────────────────────

def test_scaffold_creates_skill_md_for_skill_kind(tmp_path):
    scaffold_domain_agent = _load_scaffold().scaffold_domain_agent
    scaffold_domain_agent(
        name="k8s-query",
        kind="Skill",
        description="Kubernetes read-only query skill",
        route_keywords=["list pods", "get logs"],
        agent="quick",
        workspace_root=tmp_path,
    )
    skill_md = tmp_path / "k8s-query" / "SKILL.md"
    assert skill_md.exists(), "SKILL.md must be created for Skill kind"
    content = skill_md.read_text()
    assert "k8s-query" in content

    agent_md = tmp_path / "k8s-query" / "AGENT.md"
    assert not agent_md.exists(), "AGENT.md must NOT be created for Skill kind"


# ── 5. creates tools/ directory when requested ────────────────────────────────

def test_scaffold_creates_tools_dir(tmp_path):
    scaffold_domain_agent = _load_scaffold().scaffold_domain_agent
    scaffold_domain_agent(
        name="itsm",
        kind="Agent",
        description="ITSM agent",
        route_keywords=[],
        workspace_root=tmp_path,
        create_tools_dir=True,
    )
    tools_dir = tmp_path / "itsm" / "tools"
    assert tools_dir.is_dir(), "tools/ directory must be created"


# ── 6. return dict structure ──────────────────────────────────────────────────

def test_scaffold_returns_result_dict(tmp_path):
    scaffold_domain_agent = _load_scaffold().scaffold_domain_agent
    result = scaffold_domain_agent(
        name="itsm",
        kind="Agent",
        description="ITSM agent",
        route_keywords=["open ticket"],
        workspace_root=tmp_path,
    )
    assert isinstance(result, dict)
    assert "created_files" in result
    assert "workspace_dir" in result
    assert result["name"] == "itsm"
    assert isinstance(result["created_files"], list)
    assert len(result["created_files"]) >= 2  # at least MANIFEST.yaml + AGENT.md


# ── 7. raises ValueError for unknown kind ────────────────────────────────────

def test_scaffold_raises_for_unknown_kind(tmp_path):
    scaffold_domain_agent = _load_scaffold().scaffold_domain_agent
    with pytest.raises(ValueError, match="kind"):
        scaffold_domain_agent(
            name="bad",
            kind="Unknown",
            description="bad kind",
            route_keywords=[],
            workspace_root=tmp_path,
        )


# ── 8. idempotent — no overwrite by default ────────────────────────────────────

def test_scaffold_does_not_overwrite_existing(tmp_path):
    scaffold_domain_agent = _load_scaffold().scaffold_domain_agent
    # First call
    scaffold_domain_agent(
        name="itsm",
        kind="Agent",
        description="original",
        route_keywords=[],
        workspace_root=tmp_path,
    )
    manifest_path = tmp_path / "itsm" / "MANIFEST.yaml"
    original_mtime = manifest_path.stat().st_mtime

    # Second call — must not overwrite
    result2 = scaffold_domain_agent(
        name="itsm",
        kind="Agent",
        description="should be ignored",
        route_keywords=["new keyword"],
        workspace_root=tmp_path,
    )
    assert manifest_path.stat().st_mtime == original_mtime
    assert result2["created_files"] == []  # nothing written


# ── 9. overwrite=True replaces existing ───────────────────────────────────────

def test_scaffold_overwrite_flag(tmp_path):
    scaffold_domain_agent = _load_scaffold().scaffold_domain_agent
    scaffold_domain_agent(
        name="itsm",
        kind="Agent",
        description="original",
        route_keywords=[],
        workspace_root=tmp_path,
    )
    scaffold_domain_agent(
        name="itsm",
        kind="Agent",
        description="updated description",
        route_keywords=["new keyword"],
        workspace_root=tmp_path,
        overwrite=True,
    )
    manifest_path = tmp_path / "itsm" / "MANIFEST.yaml"
    data = yaml.safe_load(manifest_path.read_text())
    assert "new keyword" in data["route_keywords"]


# ── 10. discover_agents picks up scaffolded MANIFEST ─────────────────────────

def test_scaffold_manifest_discoverable(tmp_path):
    scaffold_domain_agent = _load_scaffold().scaffold_domain_agent
    from olav.core.agent_registry import discover_agents
    scaffold_domain_agent(
        name="itsm",
        kind="Agent",
        description="ITSM domain agent",
        route_keywords=["incident", "change"],
        workspace_root=tmp_path,
    )
    result = discover_agents(tmp_path)
    assert "itsm" in result
    assert result["itsm"].kind == "Agent"

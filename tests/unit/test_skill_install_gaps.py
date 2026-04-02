"""TDD — GAP-01, GAP-02, GAP-05: skill install + PLATFORM.md sync.

GAP-01: olav skill install works with a bare MANIFEST.yaml (no workspace.yaml)
GAP-02: install writes the new agent name into PLATFORM.md agents: list
GAP-05: olav workspace use syncs PLATFORM.md active:
"""
from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import yaml


def _make_manifest_only_skill(root: Path, name: str) -> Path:
    """Minimal skill dir: MANIFEST.yaml + AGENT.md + SKILL.md, no workspace.yaml."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "MANIFEST.yaml").write_text(yaml.dump({
        "kind": "Agent",
        "name": name,
        "version": "1.0.0",
        "description": f"{name} skill",
        "route_keywords": [name],
    }))
    (d / "AGENT.md").write_text(f"---\nname: {name}\ndescription: {name}\n---\n")
    (d / "SKILL.md").write_text(f"---\nname: {name}\ntools: []\n---\n")
    (d / "prompts").mkdir(exist_ok=True)
    (d / "prompts" / "system.md").write_text(f"You are {name}.")
    return d


def _make_workspace_yaml_skill(root: Path, name: str) -> Path:
    """Skill dir with workspace.yaml (existing behaviour)."""
    d = _make_manifest_only_skill(root, name)
    (d / "workspace.yaml").write_text(yaml.dump({
        "name": name,
        "version": "1.0.0",
        "description": f"{name} workspace",
        "requires": {"packages": [], "binaries": []},
    }))
    return d


# ── GAP-01: install from MANIFEST.yaml ──────────────────────────────────────


class TestSkillInstallManifestOnly:
    def test_install_succeeds_with_manifest_no_workspace_yaml(self, tmp_path, monkeypatch):
        """GAP-01: install a skill that has MANIFEST.yaml but no workspace.yaml."""
        monkeypatch.chdir(tmp_path)
        skill_dir = _make_manifest_only_skill(tmp_path / "skills", "netbox")

        from olav.cli.commands.skill import SkillCommand
        result = asyncio.run(SkillCommand().execute(f"install {skill_dir}"))

        assert "error" not in result.lower(), f"Unexpected error: {result}"
        assert "netbox" in result.lower()

    def test_install_creates_workspace_dir(self, tmp_path, monkeypatch):
        """GAP-01: after install, workspace dir exists in .olav/workspace/."""
        monkeypatch.chdir(tmp_path)
        skill_dir = _make_manifest_only_skill(tmp_path / "skills", "myskill")

        from olav.cli.commands.skill import SkillCommand
        asyncio.run(SkillCommand().execute(f"install {skill_dir}"))

        ws = tmp_path / ".olav" / "workspace" / "myskill"
        assert ws.exists(), f"Workspace dir not created: {ws}"
        assert (ws / "AGENT.md").exists()

    def test_install_writes_lock_file_from_manifest(self, tmp_path, monkeypatch):
        """GAP-01: lock file is written using MANIFEST.yaml metadata."""
        monkeypatch.chdir(tmp_path)
        skill_dir = _make_manifest_only_skill(tmp_path / "skills", "testskill")

        from olav.cli.commands.skill import SkillCommand
        asyncio.run(SkillCommand().execute(f"install {skill_dir}"))

        lock = tmp_path / ".olav" / "workspace" / "testskill" / "workspace.lock.yaml"
        assert lock.exists(), "Lock file not written"
        data = yaml.safe_load(lock.read_text())
        assert data["name"] == "testskill"
        assert data["version"] == "1.0.0"

    def test_install_workspace_yaml_still_works(self, tmp_path, monkeypatch):
        """GAP-01: backward compat — workspace.yaml still takes precedence."""
        monkeypatch.chdir(tmp_path)
        skill_dir = _make_workspace_yaml_skill(tmp_path / "skills", "legacyskill")

        from olav.cli.commands.skill import SkillCommand
        result = asyncio.run(SkillCommand().execute(f"install {skill_dir}"))

        assert "error" not in result.lower(), f"Unexpected error: {result}"
        ws = tmp_path / ".olav" / "workspace" / "legacyskill"
        assert ws.exists()


# ── GAP-02: PLATFORM.md updated on install ───────────────────────────────────


class TestInstallUpdatesPlatformMd:
    def test_install_adds_agent_to_platform_md_agents_list(self, tmp_path, monkeypatch):
        """GAP-02: after install, agent name appears in PLATFORM.md agents:."""
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)
        (ws_root / "PLATFORM.md").write_text(
            "---\nagents: [quick, ops]\nactive: quick\n---\n"
        )
        skill_dir = _make_manifest_only_skill(tmp_path / "skills", "netbox")

        from olav.cli.commands.skill import SkillCommand
        asyncio.run(SkillCommand().execute(f"install {skill_dir}"))

        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(ws_root)
        assert "netbox" in reg.agents

    def test_install_creates_platform_md_if_missing(self, tmp_path, monkeypatch):
        """GAP-02: if PLATFORM.md doesn't exist, create it with the new agent."""
        monkeypatch.chdir(tmp_path)
        skill_dir = _make_manifest_only_skill(tmp_path / "skills", "newskill")

        from olav.cli.commands.skill import SkillCommand
        asyncio.run(SkillCommand().execute(f"install {skill_dir}"))

        platform_md = tmp_path / ".olav" / "workspace" / "PLATFORM.md"
        assert platform_md.exists()
        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(tmp_path / ".olav" / "workspace")
        assert "newskill" in reg.agents

    def test_install_does_not_duplicate_agent_in_platform_md(self, tmp_path, monkeypatch):
        """GAP-02: reinstalling the same skill doesn't duplicate the agents entry."""
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)
        (ws_root / "PLATFORM.md").write_text(
            "---\nagents: [quick, netbox]\nactive: quick\n---\n"
        )
        skill_dir = _make_manifest_only_skill(tmp_path / "skills", "netbox")

        from olav.cli.commands.skill import SkillCommand
        asyncio.run(SkillCommand().execute(f"install {skill_dir}"))

        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(ws_root)
        assert reg.agents.count("netbox") == 1


# ── GAP-05: workspace use syncs PLATFORM.md active: ──────────────────────────


class TestWorkspaceUseSyncsPlatformMd:
    def test_workspace_use_updates_platform_md_active(self, tmp_path, monkeypatch):
        """GAP-05: olav workspace use <name> updates PLATFORM.md active: field."""
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)
        (ws_root / "PLATFORM.md").write_text(
            "---\nagents: [quick, netbox]\nactive: quick\n---\n"
        )
        (ws_root / "netbox").mkdir()
        (ws_root / "netbox" / "AGENT.md").write_text("---\nname: netbox\n---\n")

        from olav.cli.commands.workspace import WorkspaceCommand
        asyncio.run(WorkspaceCommand().execute("use netbox"))

        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(ws_root)
        assert reg.active == "netbox"

    def test_workspace_use_keeps_agents_list_intact(self, tmp_path, monkeypatch):
        """GAP-05: workspace use doesn't clobber the agents: list."""
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)
        (ws_root / "PLATFORM.md").write_text(
            "---\nagents: [quick, ops, netbox]\nactive: quick\n---\n"
        )
        (ws_root / "ops").mkdir()
        (ws_root / "ops" / "AGENT.md").write_text("---\nname: ops\n---\n")

        from olav.cli.commands.workspace import WorkspaceCommand
        asyncio.run(WorkspaceCommand().execute("use ops"))

        from olav.core.platform_registry import PlatformRegistry
        reg = PlatformRegistry.load(ws_root)
        assert reg.agents == ["quick", "ops", "netbox"]
        assert reg.active == "ops"

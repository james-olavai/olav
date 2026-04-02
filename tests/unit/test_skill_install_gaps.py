"""TDD — GAP-01, GAP-02, GAP-05, GAP-06, GAP-07: skill install + PLATFORM.md sync.

GAP-01: olav skill install works with a bare MANIFEST.yaml (no workspace.yaml)
GAP-02: install writes the new agent name into PLATFORM.md agents: list
GAP-05: olav workspace use syncs PLATFORM.md active:
GAP-06: olav skill install <git-url> clones via git then installs
GAP-07: olav skill install --merge-into appends tools into existing workspace SKILL.md
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


# ── GAP-06: git URL install ────────────────────────────────────────────────────


class TestGitUrlInstall:
    def test_is_git_url_detects_https(self):
        from olav.cli.commands.skill import _is_git_url
        assert _is_git_url("https://github.com/user/repo")
        assert _is_git_url("https://github.com/user/repo.git")

    def test_is_git_url_detects_git_at(self):
        from olav.cli.commands.skill import _is_git_url
        assert _is_git_url("git@github.com:user/repo.git")

    def test_is_git_url_rejects_local_path(self):
        from olav.cli.commands.skill import _is_git_url
        assert not _is_git_url("/home/user/myskill")
        assert not _is_git_url("./myskill")
        assert not _is_git_url("myskill")

    def test_git_clone_failure_returns_error(self, tmp_path, monkeypatch):
        """A bad URL returns status=error, does not raise."""
        import subprocess
        from unittest.mock import patch, MagicMock

        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: repository not found"

        with patch("subprocess.run", return_value=mock_result):
            from olav.cli.commands.skill import _git_clone
            result = _git_clone("https://github.com/no/such/repo.git")

        assert result["status"] == "error"
        assert "fatal" in result["error"] or "not found" in result["error"]

    def test_install_git_url_clones_and_installs(self, tmp_path, monkeypatch):
        """install <git-url> clones to temp dir, installs workspace, cleans up."""
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)
        (ws_root / "PLATFORM.md").write_text("---\nagents: []\n---\n")

        # Create a fake "cloned" skill dir
        cloned_dir = tmp_path / "_fake_clone"
        cloned_dir.mkdir()
        (cloned_dir / "MANIFEST.yaml").write_text(yaml.dump({
            "name": "git-skill", "version": "1.0.0", "kind": "Agent",
            "description": "From git", "route_keywords": ["git"],
        }))
        (cloned_dir / "SKILL.md").write_text("---\nname: git-skill\n---\n# git-skill\n")

        from unittest.mock import patch
        with patch(
            "olav.cli.commands.skill._git_clone",
            return_value={"status": "ok", "path": str(cloned_dir)},
        ):
            with patch("olav.cli.commands.skill._is_git_url", return_value=True):
                from olav.cli.commands.skill import SkillCommand
                result = asyncio.run(
                    SkillCommand().execute("install https://github.com/user/git-skill")
                )

        assert "git-skill" in result
        assert "error" not in result.lower()
        assert (ws_root / "git-skill").is_dir()


# ── GAP-07: --merge-into ──────────────────────────────────────────────────────


class TestMergeInto:
    def _make_target_workspace(self, ws_root: Path, name: str) -> Path:
        ws_dir = ws_root / name
        ws_dir.mkdir(parents=True)
        (ws_dir / "SKILL.md").write_text(
            "---\nname: existing-ws\ntools:\n- path: .olav/workspace/existing-ws/tools/old_tool.py\n---\n\n# Existing WS\n"
        )
        tools_dir = ws_dir / "tools"
        tools_dir.mkdir()
        (tools_dir / "old_tool.py").write_text("from langchain_core.tools import tool\n\n@tool\ndef old_tool(): pass\n")
        return ws_dir

    def _make_source_skill(self, source_root: Path, name: str) -> Path:
        d = source_root / name
        d.mkdir(parents=True)
        (d / "MANIFEST.yaml").write_text(yaml.dump({
            "name": name, "version": "1.0.0", "kind": "Agent",
            "description": "Pack", "route_keywords": [name],
        }))
        tools_dir = d / "tools"
        tools_dir.mkdir()
        (tools_dir / "new_tool.py").write_text(
            "from langchain_core.tools import tool\n\n@tool\ndef new_tool(): pass\n"
        )
        return d

    def test_merge_into_appends_new_tools(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)

        self._make_target_workspace(ws_root, "existing-ws")
        source_dir = self._make_source_skill(tmp_path / "skills", "pack")

        result = asyncio.run(
            __import__("olav.cli.commands.skill", fromlist=["SkillCommand"]).SkillCommand().execute(
                f"install {source_dir} --merge-into existing-ws"
            )
        )

        assert "error" not in result.lower()
        assert "new_tool" in result

        # Verify SKILL.md updated
        skill_md = ws_root / "existing-ws" / "SKILL.md"
        text = skill_md.read_text()
        assert "new_tool.py" in text
        # Old tool must still be present
        assert "old_tool.py" in text

    def test_merge_into_skips_duplicate_tools(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        ws_root.mkdir(parents=True)

        target = self._make_target_workspace(ws_root, "existing-ws")

        # Source with same filename as existing tool
        source_dir = tmp_path / "skills" / "pack"
        source_dir.mkdir(parents=True)
        (source_dir / "MANIFEST.yaml").write_text(yaml.dump({
            "name": "pack", "version": "1.0.0", "kind": "Agent",
            "description": "Pack", "route_keywords": ["pack"],
        }))
        tools_dir = source_dir / "tools"
        tools_dir.mkdir()
        # Same name as already in target
        (tools_dir / "old_tool.py").write_text(
            "from langchain_core.tools import tool\n\n@tool\ndef old_tool_v2(): pass\n"
        )

        from olav.cli.commands.skill import SkillCommand
        result = asyncio.run(SkillCommand().execute(f"install {source_dir} --merge-into existing-ws"))

        assert "no new tools" in result

    def test_merge_into_missing_target_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".olav" / "workspace").mkdir(parents=True)

        source_dir = self._make_source_skill(tmp_path / "skills", "pack")

        from olav.cli.commands.skill import SkillCommand
        result = asyncio.run(SkillCommand().execute(f"install {source_dir} --merge-into nonexistent"))

        assert "error" in result.lower()
        assert "nonexistent" in result

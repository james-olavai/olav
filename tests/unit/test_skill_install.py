"""Tests for olav skill install + WorkspaceDeclaration (P1B: declarative workspace)."""

import asyncio
import json
from pathlib import Path
from textwrap import dedent

import pytest
import yaml


# ── WorkspaceDeclaration parsing ─────────────────────────────────────────────

class TestWorkspaceDeclarationParsing:
    def test_minimal_workspace_yaml(self, tmp_path):
        from olav.core.workspace import WorkspaceDeclaration

        (tmp_path / "workspace.yaml").write_text(dedent("""\
            kind: Workspace
            name: netops
            version: "1.0.0"
            description: NetOps workspace
        """))
        decl = WorkspaceDeclaration.from_yaml(tmp_path / "workspace.yaml")
        assert decl.name == "netops"
        assert decl.version == "1.0.0"
        assert decl.description == "NetOps workspace"
        assert decl.agents == []

    def test_requires_packages_and_binaries(self, tmp_path):
        from olav.core.workspace import WorkspaceDeclaration

        (tmp_path / "workspace.yaml").write_text(dedent("""\
            kind: Workspace
            name: netops
            version: "1.0.0"
            requires:
              packages:
                - olav-netops>=0.12.0
              binaries:
                - ssh
                - nmap
              env_hint:
                - NORNIR_HOSTS_YAML
        """))
        decl = WorkspaceDeclaration.from_yaml(tmp_path / "workspace.yaml")
        assert decl.requires.packages == ["olav-netops>=0.12.0"]
        assert decl.requires.binaries == ["ssh", "nmap"]
        assert decl.requires.env_hint == ["NORNIR_HOSTS_YAML"]

    def test_agents_list(self, tmp_path):
        from olav.core.workspace import WorkspaceDeclaration

        (tmp_path / "workspace.yaml").write_text(dedent("""\
            kind: Workspace
            name: netops
            version: "1.0.0"
            agents:
              - name: ops
                kind: Agent
                description: Ops agent
                route_keywords: [show, ping, trace]
              - name: config
                kind: Agent
                description: Config agent
        """))
        decl = WorkspaceDeclaration.from_yaml(tmp_path / "workspace.yaml")
        assert len(decl.agents) == 2
        assert decl.agents[0].name == "ops"
        assert decl.agents[0].kind == "Agent"
        assert decl.agents[0].route_keywords == ["show", "ping", "trace"]
        assert decl.agents[1].name == "config"

    def test_nested_sub_agents(self, tmp_path):
        from olav.core.workspace import WorkspaceDeclaration

        (tmp_path / "workspace.yaml").write_text(dedent("""\
            kind: Workspace
            name: netops
            version: "1.0.0"
            agents:
              - name: ops
                kind: Agent
                description: Ops orchestrator
                agents:
                  - name: diff
                    kind: Skill
                    description: Diff tool
                  - name: probe
                    kind: Skill
                    description: Probe tool
        """))
        decl = WorkspaceDeclaration.from_yaml(tmp_path / "workspace.yaml")
        ops = decl.agents[0]
        assert len(ops.agents) == 2
        assert ops.agents[0].name == "diff"
        assert ops.agents[0].kind == "Skill"

    def test_set_active_flag(self, tmp_path):
        from olav.core.workspace import WorkspaceDeclaration

        (tmp_path / "workspace.yaml").write_text(dedent("""\
            kind: Workspace
            name: netops
            version: "1.0.0"
            set_active: true
        """))
        decl = WorkspaceDeclaration.from_yaml(tmp_path / "workspace.yaml")
        assert decl.set_active is True

    def test_optional_fields_defaults(self, tmp_path):
        from olav.core.workspace import WorkspaceDeclaration

        (tmp_path / "workspace.yaml").write_text("kind: Workspace\nname: test\n")
        decl = WorkspaceDeclaration.from_yaml(tmp_path / "workspace.yaml")
        assert decl.version == "0.1.0"
        assert decl.set_active is False
        assert decl.source is None
        assert decl.db_schema is None
        assert decl.init_command is None
        assert decl.requires.packages == []
        assert decl.requires.binaries == []

    def test_missing_name_raises(self, tmp_path):
        from olav.core.workspace import WorkspaceDeclaration

        (tmp_path / "workspace.yaml").write_text("kind: Workspace\nversion: 1.0\n")
        with pytest.raises(KeyError):
            WorkspaceDeclaration.from_yaml(tmp_path / "workspace.yaml")


# ── binary check helper ───────────────────────────────────────────────────────

class TestBinaryCheck:
    def test_returns_empty_when_all_available(self, tmp_path):
        from olav.core.workspace import RequiresDeclaration, check_binary_requirements

        req = RequiresDeclaration(binaries=["sh", "ls"])  # always present
        missing = check_binary_requirements(req)
        assert missing == []

    def test_returns_missing_binaries(self, tmp_path):
        from olav.core.workspace import RequiresDeclaration, check_binary_requirements

        req = RequiresDeclaration(binaries=["__nonexistent_binary_xyz__"])
        missing = check_binary_requirements(req)
        assert "__nonexistent_binary_xyz__" in missing


# ── SkillCommand install ──────────────────────────────────────────────────────

class TestSkillInstall:
    def _make_skill_repo(self, path: Path, name: str = "netops", agents: list | None = None) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        agents_yaml = ""
        if agents:
            agents_yaml = "agents:\n" + "".join(
                f"  - name: {a}\n    kind: Agent\n    description: {a} agent\n" for a in agents
            )
        (path / "workspace.yaml").write_text(
            f"kind: Workspace\nname: {name}\nversion: 1.0.0\n{agents_yaml}",
            encoding="utf-8",
        )
        return path

    def test_install_from_local_dir(self, tmp_path, monkeypatch):
        from olav.cli.commands.skill import SkillCommand

        monkeypatch.chdir(tmp_path)
        repo = self._make_skill_repo(tmp_path / "netops-skills")

        result = asyncio.run(SkillCommand().execute(f"install {repo}"))

        assert "netops" in result
        assert (tmp_path / ".olav" / "workspace" / "netops").exists()

    def test_install_writes_lock_file(self, tmp_path, monkeypatch):
        from olav.cli.commands.skill import SkillCommand

        monkeypatch.chdir(tmp_path)
        repo = self._make_skill_repo(tmp_path / "netops-skills")

        asyncio.run(SkillCommand().execute(f"install {repo}"))

        lock_path = tmp_path / ".olav" / "workspace" / "netops" / "workspace.lock.yaml"
        assert lock_path.exists(), "lock file should be written after install"
        lock = yaml.safe_load(lock_path.read_text())
        assert lock["name"] == "netops"
        assert "installed_at" in lock

    def test_install_creates_agent_subdirs(self, tmp_path, monkeypatch):
        from olav.cli.commands.skill import SkillCommand

        monkeypatch.chdir(tmp_path)
        repo = self._make_skill_repo(tmp_path / "netops-skills", agents=["ops", "config"])

        asyncio.run(SkillCommand().execute(f"install {repo}"))

        ws = tmp_path / ".olav" / "workspace" / "netops"
        assert (ws / "ops").exists()
        assert (ws / "ops" / "AGENT.md").exists()
        assert (ws / "config").exists()
        assert (ws / "config" / "AGENT.md").exists()

    def test_install_missing_workspace_yaml(self, tmp_path, monkeypatch):
        from olav.cli.commands.skill import SkillCommand

        monkeypatch.chdir(tmp_path)
        empty_dir = tmp_path / "empty-skill"
        empty_dir.mkdir()

        result = asyncio.run(SkillCommand().execute(f"install {empty_dir}"))
        assert "error" in result.lower() or "not found" in result.lower()

    def test_install_nonexistent_dir(self, tmp_path, monkeypatch):
        from olav.cli.commands.skill import SkillCommand

        monkeypatch.chdir(tmp_path)
        result = asyncio.run(SkillCommand().execute("install /nonexistent/path/xyz"))
        assert "error" in result.lower() or "not found" in result.lower()

    def test_install_warns_missing_binaries(self, tmp_path, monkeypatch):
        from olav.cli.commands.skill import SkillCommand

        monkeypatch.chdir(tmp_path)
        repo = tmp_path / "skill-repo"
        repo.mkdir()
        (repo / "workspace.yaml").write_text(dedent("""\
            kind: Workspace
            name: testskill
            version: 1.0.0
            requires:
              binaries:
                - __fake_binary_xyz__
        """))

        result = asyncio.run(SkillCommand().execute(f"install {repo}"))
        # Should still install, but warn about missing binary
        assert (tmp_path / ".olav" / "workspace" / "testskill").exists()
        assert "__fake_binary_xyz__" in result

    def test_install_set_active_updates_settings(self, tmp_path, monkeypatch):
        from olav.cli.commands.skill import SkillCommand

        monkeypatch.chdir(tmp_path)
        repo = tmp_path / "skill-repo"
        repo.mkdir()
        (repo / "workspace.yaml").write_text(dedent("""\
            kind: Workspace
            name: myworkspace
            version: 1.0.0
            set_active: true
        """))

        asyncio.run(SkillCommand().execute(f"install {repo}"))

        settings_path = tmp_path / ".olav" / "config" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert data["active_workspace"] == "myworkspace"

    def test_install_without_source_shows_usage(self, tmp_path, monkeypatch):
        from olav.cli.commands.skill import SkillCommand

        monkeypatch.chdir(tmp_path)
        result = asyncio.run(SkillCommand().execute("install"))
        assert "usage" in result.lower() or "error" in result.lower()

    def test_install_no_args_shows_usage(self, tmp_path, monkeypatch):
        from olav.cli.commands.skill import SkillCommand

        monkeypatch.chdir(tmp_path)
        result = asyncio.run(SkillCommand().execute(""))
        assert result  # non-empty response

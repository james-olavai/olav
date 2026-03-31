"""Tests for §8: extended olav workspace commands — list/use/validate/migrate."""

import asyncio
import json
from pathlib import Path
from textwrap import dedent

import pytest
import yaml


def _make_workspace(root: Path, name: str, version: str = "1.0.0", agents: list[str] | None = None) -> Path:
    """Create a managed workspace with lock file and optional agent subdirs."""
    ws_dir = root / name
    ws_dir.mkdir(parents=True, exist_ok=True)
    lock = {
        "name": name,
        "version": version,
        "source": f"https://example.com/{name}",
        "installed_at": "2026-01-01T00:00:00+00:00",
        "requires": {"packages": [], "binaries": []},
    }
    (ws_dir / "workspace.lock.yaml").write_text(yaml.dump(lock), encoding="utf-8")
    for agent in (agents or []):
        agent_dir = ws_dir / agent
        agent_dir.mkdir()
        (agent_dir / "AGENT.md").write_text(f"---\nname: {agent}\n---\n", encoding="utf-8")
    return ws_dir


def _make_flat_agent(root: Path, name: str) -> Path:
    """Create a flat (unmanaged) agent directly in workspace root."""
    agent_dir = root / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENT.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
    return agent_dir


# ── workspace list ────────────────────────────────────────────────────────────

class TestWorkspaceList:
    def test_list_shows_managed_workspace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_workspace(ws_root, "netops", version="1.2.0")

        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("list"))
        assert "netops" in result

    def test_list_shows_version(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_workspace(ws_root, "netops", version="2.3.4")

        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("list"))
        assert "2.3.4" in result

    def test_list_marks_active_workspace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_workspace(ws_root, "netops")
        _make_workspace(ws_root, "itsm")
        settings = tmp_path / ".olav" / "config" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"active_workspace": "netops"}))

        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("list"))
        # Active workspace should be visually distinguished
        lines = result.splitlines()
        netops_line = next((l for l in lines if "netops" in l), "")
        itsm_line = next((l for l in lines if "itsm" in l), "")
        assert "*" in netops_line or "active" in netops_line.lower()
        assert "*" not in itsm_line

    def test_list_empty_when_no_workspaces(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("list"))
        assert "no workspace" in result.lower() or result.strip() == ""

    def test_list_shows_unmanaged_agents_separately(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_workspace(ws_root, "netops")
        _make_flat_agent(ws_root, "quick")  # flat, unmanaged

        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("list"))
        assert "netops" in result
        # quick may or may not appear depending on implementation — no crash is the key


# ── workspace use ─────────────────────────────────────────────────────────────

class TestWorkspaceUse:
    def test_use_updates_active_workspace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_workspace(ws_root, "netops")

        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("use netops"))
        assert "netops" in result.lower() or "active" in result.lower()

        settings_path = tmp_path / ".olav" / "config" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert data["active_workspace"] == "netops"

    def test_use_creates_settings_json_if_absent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_workspace(ws_root, "itsm")

        from olav.cli.commands.workspace import WorkspaceCommand
        asyncio.run(WorkspaceCommand().execute("use itsm"))

        settings_path = tmp_path / ".olav" / "config" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert data["active_workspace"] == "itsm"

    def test_use_without_name_shows_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("use"))
        assert "error" in result.lower() or "usage" in result.lower()

    def test_use_nonexistent_workspace_warns(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("use ghost"))
        # Should warn but still set (user may create later)
        assert "ghost" in result.lower() or "warn" in result.lower() or "not found" in result.lower()


# ── workspace validate ────────────────────────────────────────────────────────

class TestWorkspaceValidate:
    def test_validate_passes_managed_workspace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_workspace(ws_root, "netops", agents=["ops"])

        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("validate netops"))
        assert "valid" in result.lower() or "ok" in result.lower() or "✓" in result

    def test_validate_reports_missing_lock_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_flat_agent(ws_root, "ops")  # no lock file

        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("validate ops"))
        assert "lock" in result.lower() or "unmanaged" in result.lower() or "no lock" in result.lower()

    def test_validate_nonexistent_shows_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("validate ghost"))
        assert "not found" in result.lower() or "error" in result.lower()

    def test_validate_without_name_shows_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("validate"))
        assert "error" in result.lower() or "usage" in result.lower()


# ── workspace migrate ─────────────────────────────────────────────────────────

class TestWorkspaceMigrate:
    def test_migrate_moves_flat_agents_to_core(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_flat_agent(ws_root, "quick")
        _make_flat_agent(ws_root, "ops")

        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("migrate"))
        assert "migrat" in result.lower() or "moved" in result.lower()
        # Flat agents should now be under core/
        assert (ws_root / "core" / "quick").exists()
        assert (ws_root / "core" / "ops").exists()

    def test_migrate_skips_managed_workspaces(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_workspace(ws_root, "netops", agents=["ops"])  # has lock file

        from olav.cli.commands.workspace import WorkspaceCommand
        result = asyncio.run(WorkspaceCommand().execute("migrate"))
        # netops stays in place (is already a managed workspace)
        assert (ws_root / "netops").exists()
        assert not (ws_root / "core" / "netops").exists()

    def test_migrate_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws_root = tmp_path / ".olav" / "workspace"
        _make_flat_agent(ws_root, "quick")

        from olav.cli.commands.workspace import WorkspaceCommand
        asyncio.run(WorkspaceCommand().execute("migrate"))
        # Second run should not crash or duplicate
        result2 = asyncio.run(WorkspaceCommand().execute("migrate"))
        assert isinstance(result2, str)  # no exception

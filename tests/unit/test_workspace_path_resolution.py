"""Tests for resolve_workspace_path() and get_active_workspace() (§11.6)."""

import json
from pathlib import Path

import pytest


# ── get_active_workspace ──────────────────────────────────────────────────────

class TestGetActiveWorkspace:
    def test_defaults_to_core_when_no_settings(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from olav.core.workspace import get_active_workspace
        assert get_active_workspace() == "core"

    def test_reads_from_settings_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        settings = tmp_path / ".olav" / "config" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"active_workspace": "netops"}))
        from importlib import reload
        import olav.core.workspace as ws_mod
        reload(ws_mod)  # flush module-level cache if any
        from olav.core.workspace import get_active_workspace
        assert get_active_workspace() == "netops"

    def test_tolerates_broken_settings(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        settings = tmp_path / ".olav" / "config" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text("not valid json {{")
        from olav.core.workspace import get_active_workspace
        assert get_active_workspace() == "core"

    def test_missing_key_returns_core(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        settings = tmp_path / ".olav" / "config" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"some_other_key": "value"}))
        from olav.core.workspace import get_active_workspace
        assert get_active_workspace() == "core"


# ── resolve_workspace_path ────────────────────────────────────────────────────

class TestResolveWorkspacePath:
    def _workspace_root(self, tmp_path: Path) -> Path:
        return tmp_path / ".olav" / "workspace"

    def test_flat_path_returned_when_it_exists(self, tmp_path, monkeypatch):
        """Flat structure takes priority for backward compat."""
        monkeypatch.chdir(tmp_path)
        flat_dir = tmp_path / ".olav" / "workspace" / "audit" / "profiles"
        flat_dir.mkdir(parents=True)
        from olav.core.workspace import resolve_workspace_path
        result = resolve_workspace_path("audit", "profiles")
        assert result == flat_dir

    def test_nested_path_returned_when_flat_absent(self, tmp_path, monkeypatch):
        """Nested structure used when flat path does not exist."""
        monkeypatch.chdir(tmp_path)
        settings = tmp_path / ".olav" / "config" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"active_workspace": "netops"}))
        from olav.core.workspace import resolve_workspace_path
        result = resolve_workspace_path("ops", "tools")
        expected = tmp_path / ".olav" / "workspace" / "netops" / "ops" / "tools"
        assert result == expected

    def test_explicit_workspace_overrides_active(self, tmp_path, monkeypatch):
        """workspace= kwarg overrides active workspace from settings."""
        monkeypatch.chdir(tmp_path)
        settings = tmp_path / ".olav" / "config" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"active_workspace": "netops"}))
        from olav.core.workspace import resolve_workspace_path
        result = resolve_workspace_path("ops", workspace="itsm")
        expected = tmp_path / ".olav" / "workspace" / "itsm" / "ops"
        assert result == expected

    def test_no_parts_returns_workspace_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from olav.core.workspace import resolve_workspace_path
        result = resolve_workspace_path()
        assert result == tmp_path / ".olav" / "workspace"

    def test_no_parts_with_workspace_returns_workspace_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from olav.core.workspace import resolve_workspace_path
        result = resolve_workspace_path(workspace="netops")
        assert result == tmp_path / ".olav" / "workspace" / "netops"

    def test_custom_workspace_root(self, tmp_path):
        """Custom workspace_root kwarg used instead of default .olav/workspace."""
        custom_root = tmp_path / "custom_ws"
        flat_dir = custom_root / "audit"
        flat_dir.mkdir(parents=True)
        from olav.core.workspace import resolve_workspace_path
        result = resolve_workspace_path("audit", workspace_root=custom_root)
        assert result == flat_dir

    def test_single_part_flat_agent(self, tmp_path, monkeypatch):
        """resolve_workspace_path('quick') returns flat quick dir if it exists."""
        monkeypatch.chdir(tmp_path)
        quick_dir = tmp_path / ".olav" / "workspace" / "quick"
        quick_dir.mkdir(parents=True)
        from olav.core.workspace import resolve_workspace_path
        result = resolve_workspace_path("quick")
        assert result == quick_dir

    def test_core_default_when_no_settings_and_flat_absent(self, tmp_path, monkeypatch):
        """Falls back to 'core' workspace when no settings and no flat path."""
        monkeypatch.chdir(tmp_path)
        from olav.core.workspace import resolve_workspace_path
        result = resolve_workspace_path("ops")
        expected = tmp_path / ".olav" / "workspace" / "core" / "ops"
        assert result == expected


# ── resolve_workspace_root ────────────────────────────────────────────────────

class TestResolveWorkspaceRoot:
    def test_returns_workspace_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from olav.core.workspace import resolve_workspace_root
        result = resolve_workspace_root()
        assert result == tmp_path / ".olav" / "workspace"

    def test_returns_named_workspace_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from olav.core.workspace import resolve_workspace_root
        result = resolve_workspace_root("netops")
        assert result == tmp_path / ".olav" / "workspace" / "netops"

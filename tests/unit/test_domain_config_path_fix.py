"""TDD tests for ISSUE-P0-DOMAIN-CONFIG-PATH-BROKEN.

Verifies that after the config architecture migration:
- get_domain_config_dir("netops") returns the workspace ops/config path
- NORNIR_CONFIG_PATH resolves to workspace ops/config/nornir/config.yaml
- CommandRegistry loads blacklist/whitelist from workspace config dir

Gate conditions (from dev_docs/00. issues.md):
- get_domain_config_dir("netops") returns .olav/workspace/ops/config/
- CommandRegistry loads whitelist/blacklist from workspace config files
- Modifying workspace/ops/config/blacklisted_commands.yaml + reload() takes effect
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# get_domain_config_dir — workspace path resolution
# ---------------------------------------------------------------------------


class TestGetDomainConfigDirWorkspacePath:
    """get_domain_config_dir must return workspace path when it exists."""

    def test_returns_workspace_path_when_exists(self, tmp_path, monkeypatch):
        """When workspace ops/config exists, return it instead of legacy path."""
        ws_config = tmp_path / "workspace" / "ops" / "config"
        ws_config.mkdir(parents=True)

        monkeypatch.setattr("olav.core.config.AGENT_DIR", tmp_path)
        monkeypatch.setattr("olav.core.config.CONFIG_DIR", tmp_path / "config")

        from olav.core.config import get_domain_config_dir

        result = get_domain_config_dir("netops")
        assert result == ws_config, (
            f"Expected {ws_config}, got {result} — "
            "get_domain_config_dir must return workspace path when it exists"
        )

    def test_fallback_to_legacy_when_workspace_missing(self, tmp_path, monkeypatch):
        """When workspace ops/config does not exist, fall back to legacy path."""
        monkeypatch.setattr("olav.core.config.AGENT_DIR", tmp_path)
        monkeypatch.setattr("olav.core.config.CONFIG_DIR", tmp_path / "config")

        from olav.core.config import get_domain_config_dir

        result = get_domain_config_dir("netops")
        expected = tmp_path / "config" / "domains" / "netops"
        assert result == expected, (
            f"Expected legacy path {expected}, got {result}"
        )

    def test_unknown_domain_returns_legacy_path(self, tmp_path, monkeypatch):
        """Unknown domains without workspace mapping return the legacy path."""
        monkeypatch.setattr("olav.core.config.AGENT_DIR", tmp_path)
        monkeypatch.setattr("olav.core.config.CONFIG_DIR", tmp_path / "config")

        from olav.core.config import get_domain_config_dir

        result = get_domain_config_dir("someotherdomain")
        assert result == tmp_path / "config" / "domains" / "someotherdomain"

    def test_integration_actual_filesystem_returns_workspace(self):
        """Integration: real filesystem must return workspace/ops/config (post-migration)."""
        from olav.core.config import get_domain_config_dir

        result = get_domain_config_dir("netops")
        assert result.exists(), (
            f"{result} does not exist — workspace ops/config not found"
        )
        assert "workspace" in str(result), (
            f"{result} does not contain 'workspace' — not returning migrated path"
        )
        assert result.name == "config"


# ---------------------------------------------------------------------------
# NORNIR_CONFIG_PATH — workspace path resolution
# ---------------------------------------------------------------------------


class TestNornirConfigPathResolution:
    """NORNIR_CONFIG_PATH must resolve to workspace ops/config/nornir after migration."""

    def test_nornir_config_path_exists(self):
        """NORNIR_CONFIG_PATH must point to an existing file."""
        from olav.core.config import NORNIR_CONFIG_PATH

        assert NORNIR_CONFIG_PATH.exists(), (
            f"NORNIR_CONFIG_PATH={NORNIR_CONFIG_PATH} does not exist"
        )

    def test_nornir_config_path_in_workspace(self):
        """NORNIR_CONFIG_PATH must be under workspace/ops/config after migration."""
        from olav.core.config import NORNIR_CONFIG_PATH

        assert "workspace" in str(NORNIR_CONFIG_PATH), (
            f"NORNIR_CONFIG_PATH={NORNIR_CONFIG_PATH} is not under workspace/ — "
            "expected workspace/ops/config/nornir/config.yaml"
        )


# ---------------------------------------------------------------------------
# Gate condition: CommandRegistry loads from workspace config
# ---------------------------------------------------------------------------


class TestCommandRegistryLoadsFromWorkspace:
    """CommandRegistry must load blacklist/whitelist from workspace ops/config."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        from olav_netops.command_registry import CommandRegistry

        CommandRegistry._instance = None
        CommandRegistry._templates = {}
        CommandRegistry._template_index = {}
        CommandRegistry._whitelist = set()
        CommandRegistry._blacklist = []
        CommandRegistry._commands_by_platform = {}
        yield
        CommandRegistry._instance = None
        CommandRegistry._templates = {}
        CommandRegistry._template_index = {}
        CommandRegistry._whitelist = set()
        CommandRegistry._blacklist = []
        CommandRegistry._commands_by_platform = {}

    def test_netops_config_dir_resolves_to_workspace(self):
        """NETOPS_CONFIG_DIR at import time must point to workspace/ops/config."""
        import importlib
        import olav_netops.command_registry as mod

        # Force reload to re-evaluate NETOPS_CONFIG_DIR with current get_domain_config_dir
        importlib.reload(mod)
        assert "workspace" in str(mod.NETOPS_CONFIG_DIR), (
            f"NETOPS_CONFIG_DIR={mod.NETOPS_CONFIG_DIR} — not workspace path. "
            "get_domain_config_dir must be fixed to return workspace path."
        )
        assert mod.NETOPS_CONFIG_DIR.exists(), (
            f"NETOPS_CONFIG_DIR={mod.NETOPS_CONFIG_DIR} does not exist"
        )

    def test_blacklist_loads_from_workspace_config(self, tmp_path, monkeypatch):
        """After fix: blacklist in workspace/ops/config/ is loaded by CommandRegistry."""
        import yaml
        from olav_netops.command_registry import CommandRegistry

        # Point NETOPS_CONFIG_DIR to tmp_path and put blacklist there
        bl_path = tmp_path / "blacklisted_commands.yaml"
        bl_path.write_text(yaml.dump(["conf.*", "reload"]))
        monkeypatch.setattr("olav_netops.command_registry.NETOPS_CONFIG_DIR", tmp_path)

        CommandRegistry()
        assert CommandRegistry.is_command_blacklisted("configure terminal"), (
            "blacklist from workspace config must be loaded"
        )

    def test_reload_picks_up_workspace_blacklist_changes(self, tmp_path, monkeypatch):
        """CommandRegistry.reload() must pick up changes in workspace blacklist."""
        import yaml
        from olav_netops.command_registry import CommandRegistry

        bl_path = tmp_path / "blacklisted_commands.yaml"
        bl_path.write_text(yaml.dump(["shutdown"]))
        monkeypatch.setattr("olav_netops.command_registry.NETOPS_CONFIG_DIR", tmp_path)

        CommandRegistry()
        assert CommandRegistry.is_command_blacklisted("shutdown")

        # Update the workspace blacklist
        bl_path.write_text(yaml.dump(["shutdown", "reload"]))
        CommandRegistry.reload()
        assert CommandRegistry.is_command_blacklisted("reload"), (
            "CommandRegistry.reload() must pick up new workspace blacklist entries"
        )

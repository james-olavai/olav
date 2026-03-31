"""Tests that CommandRegistry uses NETOPS_CONFIG_DIR for all config paths.

Verifies the migration from legacy paths (.olav/config/textfsm, .olav/templates,
.olav/config/allowed_commands.json) to the standardised domains/netops/ namespace.
"""

from __future__ import annotations

import inspect
import json
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _source_lines() -> str:
    """Return the full source of command_registry._load_templates + _load_whitelist."""
    from olav_netops.command_registry import CommandRegistry

    src_templates = inspect.getsource(CommandRegistry._load_templates)
    src_whitelist = inspect.getsource(CommandRegistry._load_whitelist)
    return src_templates + "\n" + src_whitelist


# ---------------------------------------------------------------------------
# Source-level checks — legacy paths must NOT appear
# ---------------------------------------------------------------------------


class TestLegacyPathsRemoved:
    """Verify that legacy config paths are absent from the source code."""

    def test_no_legacy_textfsm_path(self):
        """'.olav/config/textfsm' must not be referenced."""
        src = _source_lines()
        assert ".olav/config/textfsm" not in src, (
            "_load_templates still references the legacy .olav/config/textfsm path"
        )

    def test_no_legacy_templates_dir_fallback(self):
        """getattr(…, 'templates_dir', '.olav/templates') fallback must be gone."""
        src = _source_lines()
        assert ".olav/templates" not in src, (
            "_load_templates still references the legacy .olav/templates path"
        )

    def test_no_legacy_whitelist_path(self):
        """'.olav/config/allowed_commands.json' must not appear."""
        src = _source_lines()
        assert ".olav/config/allowed_commands.json" not in src, (
            "_load_whitelist still references the legacy allowed_commands.json path"
        )

    def test_no_getattr_templates_dir(self):
        """No getattr(paths_config, 'templates_dir', ...) pattern."""
        src = _source_lines()
        assert "templates_dir" not in src, (
            "_load_templates still uses getattr templates_dir fallback"
        )


# ---------------------------------------------------------------------------
# Source-level checks — NETOPS_CONFIG_DIR must be used
# ---------------------------------------------------------------------------


class TestNetopsConfigDirUsed:
    """Verify NETOPS_CONFIG_DIR is derived from get_domain_config_dir and used."""

    def test_import_netops_config_dir(self):
        """command_registry must define NETOPS_CONFIG_DIR using get_domain_config_dir."""
        import olav_netops.command_registry as mod

        src = inspect.getsource(mod)
        assert "NETOPS_CONFIG_DIR" in src, (
            "NETOPS_CONFIG_DIR is not referenced in command_registry.py"
        )
        assert "get_domain_config_dir" in src, (
            "command_registry must use get_domain_config_dir to derive NETOPS_CONFIG_DIR"
        )

    def test_load_templates_uses_netops_config_dir(self):
        """_load_templates must reference NETOPS_CONFIG_DIR."""
        from olav_netops.command_registry import CommandRegistry

        src = inspect.getsource(CommandRegistry._load_templates)
        assert "NETOPS_CONFIG_DIR" in src, "_load_templates does not use NETOPS_CONFIG_DIR"

    def test_load_whitelist_uses_netops_config_dir(self):
        """_load_whitelist must reference NETOPS_CONFIG_DIR."""
        from olav_netops.command_registry import CommandRegistry

        src = inspect.getsource(CommandRegistry._load_whitelist)
        assert "NETOPS_CONFIG_DIR" in src, "_load_whitelist does not use NETOPS_CONFIG_DIR"


# ---------------------------------------------------------------------------
# Functional checks — templates loaded from correct directory
# ---------------------------------------------------------------------------


class TestTemplateLoadingPaths:
    """Verify _load_templates scans the correct directories."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        """Reset CommandRegistry singleton between tests."""
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

    def test_custom_textfsm_in_netops_dir(self, tmp_path, monkeypatch):
        """Priority 1: custom templates from NETOPS_CONFIG_DIR / 'textfsm'."""
        from olav_netops.command_registry import CommandRegistry

        # Set NETOPS_CONFIG_DIR to tmp_path
        monkeypatch.setattr("olav_netops.command_registry.NETOPS_CONFIG_DIR", tmp_path)

        # Create the textfsm directory with a sample template
        textfsm_dir = tmp_path / "textfsm"
        textfsm_dir.mkdir(parents=True)
        template = textfsm_dir / "cisco_ios_show_version.textfsm"
        template.write_text("Value VERSION (\\S+)\n\nStart\n  ^${VERSION}\n")

        reg = CommandRegistry.__new__(CommandRegistry)
        reg._templates = {}
        reg._template_index = {}
        reg._load_templates()

        assert "cisco_ios_show_version.textfsm" in reg._templates
        assert reg._templates["cisco_ios_show_version.textfsm"] == template
        assert reg._template_index["cisco_ios_show_version.textfsm"]["priority"] == 1

    def test_custom_templates_in_netops_dir(self, tmp_path, monkeypatch):
        """Priority 2: custom templates from NETOPS_CONFIG_DIR / 'templates' / 'custom'."""
        from olav_netops.command_registry import CommandRegistry

        monkeypatch.setattr("olav_netops.command_registry.NETOPS_CONFIG_DIR", tmp_path)

        custom_dir = tmp_path / "templates" / "custom"
        custom_dir.mkdir(parents=True)
        template = custom_dir / "arista_eos_show_bgp.textfsm"
        template.write_text("Value BGP (\\S+)\n\nStart\n  ^${BGP}\n")

        reg = CommandRegistry.__new__(CommandRegistry)
        reg._templates = {}
        reg._template_index = {}
        reg._load_templates()

        assert "arista_eos_show_bgp.textfsm" in reg._templates
        assert reg._template_index["arista_eos_show_bgp.textfsm"]["priority"] == 2

    def test_default_templates_in_netops_dir(self, tmp_path, monkeypatch):
        """Priority 3: default templates from NETOPS_CONFIG_DIR / 'templates'."""
        from olav_netops.command_registry import CommandRegistry

        monkeypatch.setattr("olav_netops.command_registry.NETOPS_CONFIG_DIR", tmp_path)

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir(parents=True)
        template = templates_dir / "juniper_junos_show_route.textfsm"
        template.write_text("Value ROUTE (\\S+)\n\nStart\n  ^${ROUTE}\n")

        reg = CommandRegistry.__new__(CommandRegistry)
        reg._templates = {}
        reg._template_index = {}
        reg._load_templates()

        assert "juniper_junos_show_route.textfsm" in reg._templates
        assert reg._template_index["juniper_junos_show_route.textfsm"]["priority"] == 3


# ---------------------------------------------------------------------------
# Functional checks — whitelist loaded from correct path
# ---------------------------------------------------------------------------


class TestWhitelistLoadingPath:
    """Verify _load_whitelist reads from NETOPS_CONFIG_DIR."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
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

    def test_whitelist_from_netops_config_dir(self, tmp_path, monkeypatch):
        """Whitelist loaded from NETOPS_CONFIG_DIR / 'allowed_commands.json'."""
        from olav_netops.command_registry import CommandRegistry

        monkeypatch.setattr("olav_netops.command_registry.NETOPS_CONFIG_DIR", tmp_path)

        whitelist_file = tmp_path / "allowed_commands.json"
        whitelist_file.write_text(json.dumps({"commands": ["show version", "show ip route"]}))

        reg = CommandRegistry.__new__(CommandRegistry)
        reg._whitelist = set()
        reg._load_whitelist()

        assert "show version" in reg._whitelist
        assert "show ip route" in reg._whitelist

    def test_whitelist_missing_file_no_error(self, tmp_path, monkeypatch):
        """No error when whitelist file does not exist."""
        from olav_netops.command_registry import CommandRegistry

        monkeypatch.setattr("olav_netops.command_registry.NETOPS_CONFIG_DIR", tmp_path)

        reg = CommandRegistry.__new__(CommandRegistry)
        reg._whitelist = set()
        reg._load_whitelist()

        assert len(reg._whitelist) == 0

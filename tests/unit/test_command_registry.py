"""Comprehensive unit tests for command registry module.

Run: pytest tests/unit/test_command_registry_comprehensive.py -v
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import olav.core.config as _olav_config
import pytest
import yaml
from src.olav.core.command_registry import CommandRegistry


@pytest.fixture
def mock_olav_dir(tmp_path, monkeypatch):
    """Create a mock .olav directory structure."""
    # Redirect _PROJECT_ROOT so PathsConfig serves paths inside tmp_path
    monkeypatch.setattr(_olav_config, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(_olav_config, "_CONFIG_DIR", tmp_path / ".olav" / "config")
    # Whitelist is loaded via CWD-relative path, so chdir as well
    monkeypatch.chdir(tmp_path)

    olav_dir = tmp_path / ".olav"
    olav_dir.mkdir()

    config_dir = olav_dir / "config"
    config_dir.mkdir()

    templates_dir = olav_dir / "templates"
    templates_dir.mkdir()

    custom_templates_dir = templates_dir / "custom"
    custom_templates_dir.mkdir()

    textfsm_config_dir = config_dir / "textfsm"
    textfsm_config_dir.mkdir()

    # Create some dummy TextFSM template files
    (templates_dir / "default.textfsm").write_text("Value Default (.*)")
    (custom_templates_dir / "custom.textfsm").write_text("Value Custom (.*)")
    (textfsm_config_dir / "priority.textfsm").write_text("Value Priority (.*)")

    # Whitelist — JSON format as read by _load_whitelist()
    whitelist_path = config_dir / "allowed_commands.json"
    whitelist_path.write_text(json.dumps({"commands": ["show version", "show ip int brief"]}))

    # Blacklist — YAML format as read by _load_blacklist()
    blacklist_path = config_dir / "blacklisted_commands.yaml"
    blacklist_path.write_text(yaml.dump(["rm -rf", "format"]))

    # Reset singleton before and after so tests use their own isolated instance
    CommandRegistry._instance = None

    yield tmp_path

    CommandRegistry._instance = None


class TestCommandRegistryComprehensive:
    """Comprehensive tests for src/olav/core/command_registry.py"""

    def test_singleton_reset(self, mock_olav_dir):
        """Test that singleton is reset and loads from mock dir."""
        registry = CommandRegistry()
        assert "default.textfsm" in registry._templates
        assert "custom.textfsm" in registry._templates
        assert "priority.textfsm" in registry._templates

    def test_template_priorities(self, mock_olav_dir):
        """Test that templates are loaded with correct priorities."""
        # Create a template with same name in different directories
        (mock_olav_dir / ".olav" / "templates" / "conflict.textfsm").write_text("default")
        (mock_olav_dir / ".olav" / "config" / "textfsm" / "conflict.textfsm").write_text("priority")

        registry = CommandRegistry()
        registry.reload()

        template_info = registry.get_all_templates().get("conflict.textfsm")
        assert template_info is not None
        # Priority 1 is highest (config/textfsm)
        assert template_info["priority"] == 1
        assert "config/textfsm" in template_info["path"]

    def test_whitelist_logic(self, mock_olav_dir):
        """Test command whitelist logic."""
        assert CommandRegistry.is_command_allowed("show version") is True
        assert CommandRegistry.is_command_allowed("show ip int brief") is True
        assert CommandRegistry.is_command_allowed("show run") is False

    def test_blacklist_logic(self, mock_olav_dir):
        """Test command blacklist logic."""
        assert CommandRegistry.is_command_blacklisted("rm -rf /") is True
        assert CommandRegistry.is_command_blacklisted("format flash:") is True
        assert CommandRegistry.is_command_blacklisted("show version") is False
        # Case insensitive
        assert CommandRegistry.is_command_blacklisted("RM -RF /") is True

    def test_reload_detects_changes(self, mock_olav_dir):
        """Test that reload detects new templates."""
        CommandRegistry()  # ensure singleton initialised

        # Add a new template
        (mock_olav_dir / ".olav" / "templates" / "new.textfsm").write_text("Value New (.*)")

        result = CommandRegistry.reload()
        assert "new.textfsm" in result["new_templates"]
        assert result["reloaded"]["templates"] == 4  # default, custom, priority, new

    def test_reload_error_handling(self, mock_olav_dir):
        """Test reload error handling with malformed JSON."""
        # Corrupt whitelist JSON
        (mock_olav_dir / ".olav" / "config" / "allowed_commands.json").write_text("{invalid json}")

        # reload() itself catches exceptions in _load_whitelist and _load_blacklist
        # but it doesn't return them in "errors" unless _load_all fails.
        # Actually _load_whitelist logs error but doesn't raise.

        result = CommandRegistry.reload()
        # Whitelist should be empty now because it failed to load
        assert len(CommandRegistry()._whitelist) == 0
        assert result["reloaded"]["whitelisted_commands"] == 0

    def test_get_template_path(self, mock_olav_dir):
        """Test get_template_path returns correct Path object."""
        path = CommandRegistry.get_template_path("default.textfsm")
        assert path is not None
        assert path.name == "default.textfsm"
        assert path.exists()

    def test_get_all_templates_metadata(self, mock_olav_dir):
        """Test metadata returned by get_all_templates."""
        templates = CommandRegistry.get_all_templates()
        assert "default.textfsm" in templates
        meta = templates["default.textfsm"]
        assert "path" in meta
        assert "priority" in meta
        assert "size" in meta
        assert meta["size"] > 0

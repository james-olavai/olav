"""Unit tests for new cli_tool.py (template discovery & blacklist)."""

import pytest
from pathlib import Path
from olav.tools.cli_tool import CommandBlacklist, TemplateManager, CLITemplateTool
from olav.tools.base import ToolOutput


class TestCommandBlacklist:
    def test_defaults(self):
        bl = CommandBlacklist()
        assert {"traceroute", "reload", "write erase", "format", "delete"}.issubset(bl.blacklist)

    def test_matching(self):
        bl = CommandBlacklist()
        assert bl.is_blocked("reload")
        assert bl.is_blocked("reload in 5")
        assert bl.is_blocked("traceroute 1.1.1.1")
        assert not bl.is_blocked("show version")

    def test_case_insensitive(self):
        bl = CommandBlacklist()
        assert bl.is_blocked("ReLoAd")

    def test_load_file(self, tmp_path: Path):
        f = tmp_path / "blk.yaml"
        f.write_text("- custom_danger\n")
        bl = CommandBlacklist(blacklist_file=f)
        assert bl.is_blocked("custom_danger")


class TestTemplateManager:
    def test_parse_filename(self):
        m = TemplateManager()
        assert m._parse_command_from_filename("cisco_ios_show_running.textfsm") == "show running-config"
        assert m._parse_command_from_filename("invalid.textfsm") is None

    def test_empty_detection(self, tmp_path: Path):
        m = TemplateManager()
        full = tmp_path / "cisco_ios_show_version.textfsm"
        full.write_text("Value VERSION (.+)\nStart\n ^X -> Record")
        empty = tmp_path / "cisco_ios_show_running.textfsm"
        empty.write_text("# comment\n# another")
        assert not m._is_template_empty(full)
        assert m._is_template_empty(empty)

    def test_caching_and_alias(self, tmp_path: Path):
        tdir = tmp_path / "templates"
        tdir.mkdir()
        (tdir / "cisco_ios_show_version.textfsm").write_text("Value VERSION (.+)")
        m = TemplateManager(templates_dir=tdir)
        first = m.get_commands_for_platform("cisco_ios")
        second = m.get_commands_for_platform("cisco_ios")
        assert first == second and len(first) == 1
        alias = m.get_commands_for_platform("ios")
        assert len(alias) == 1

    def test_get_command_template(self, tmp_path: Path):
        tdir = tmp_path / "templates"
        tdir.mkdir()
        (tdir / "cisco_ios_show_version.textfsm").write_text("Value VERSION (.+)")
        m = TemplateManager(templates_dir=tdir)
        tpl = m.get_command_template("cisco_ios", "show version")
        assert tpl and tpl[0].name.endswith("show_version.textfsm")
        assert m.get_command_template("cisco_ios", "show foo") is None

    def test_fallback_commands_cisco_ios(self, tmp_path: Path):
        """Test fallback to 91 standard Cisco IOS commands when no templates found."""
        tdir = tmp_path / "templates"
        tdir.mkdir()
        m = TemplateManager(templates_dir=tdir)
        cmds = m.get_commands_for_platform("cisco_ios")
        assert len(cmds) == 91
        cmd_names = {c[0] for c in cmds}
        assert "show version" in cmd_names
        assert "show ip interface brief" in cmd_names
        assert "show running-config" in cmd_names

    def test_fallback_commands_unknown_platform(self, tmp_path: Path):
        """Test minimal fallback for unknown platforms."""
        tdir = tmp_path / "templates"
        tdir.mkdir()
        m = TemplateManager(templates_dir=tdir)
        cmds = m.get_commands_for_platform("unknown_vendor_os")
        assert len(cmds) == 1
        assert cmds[0][0] == "show running-config"


@pytest.mark.asyncio
class TestCLITemplateTool:
    async def test_list_all(self, tmp_path: Path):
        tdir = tmp_path / "templates"
        tdir.mkdir()
        (tdir / "cisco_ios_show_version.textfsm").write_text("Value VERSION (.+)")
        tool = CLITemplateTool(templates_dir=tdir)
        out = await tool.execute(platform="cisco_ios", list_all=True)
        assert out.device == "platform" and out.source == "cli_template"
        assert out.metadata["total_commands"] == 1
        assert out.data[0]["command"] == "show version"

    async def test_lookup_specific(self, tmp_path: Path):
        tdir = tmp_path / "templates"
        tdir.mkdir()
        (tdir / "cisco_ios_show_version.textfsm").write_text("Value VERSION (.+)")
        tool = CLITemplateTool(templates_dir=tdir)
        out = await tool.execute(platform="cisco_ios", command="show version")
        d = out.data[0]
        assert d["available"] and d["parsed"] and not d["blacklisted"]

    async def test_blacklisted(self):
        tool = CLITemplateTool()
        out = await tool.execute(platform="cisco_ios", command="reload")
        assert out.error and out.data[0]["blacklisted"]

    async def test_nonexistent(self, tmp_path: Path):
        tdir = tmp_path / "templates"
        tdir.mkdir()
        tool = CLITemplateTool(templates_dir=tdir)
        out = await tool.execute(platform="cisco_ios", command="show foo")
        assert out.data[0]["available"] is False

    async def test_no_templates(self, tmp_path: Path):
        """Test fallback behavior when no templates exist for unknown platform."""
        tdir = tmp_path / "templates"
        tdir.mkdir()
        tool = CLITemplateTool(templates_dir=tdir)
        out = await tool.execute(platform="unknown_platform", list_all=True)
        # Should return fallback command (show running-config)
        assert not out.error
        assert len(out.data) == 1
        assert out.data[0]["command"] == "show running-config"
        assert out.data[0]["template"] is None  # No template file for fallback

    async def test_missing_params(self):
        tool = CLITemplateTool()
        out = await tool.execute(platform="cisco_ios")
        assert out.error and out.data[0]["status"] == "PARAM_ERROR"


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / "data" / "ntc-templates").exists(),
    reason="ntc-templates not found in data/ directory"
)
@pytest.mark.asyncio
class TestCLITemplateToolIntegration:
    async def test_real_list(self):
        tool = CLITemplateTool()
        out = await tool.execute(platform="cisco_ios", list_all=True)
        assert isinstance(out, ToolOutput) and len(out.data) > 10
    async def test_real_lookup(self):
        tool = CLITemplateTool()
        out = await tool.execute(platform="cisco_ios", command="show version")
        assert out.data[0]["available"] is True


"""Tests for dynamic /help output and removal of netops stubs from builtin.py."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from olav.cli.commands.builtin import SLASH_COMMANDS, cmd_help
from olav.cli.commands.registry import SlashCommandSpec


# ---------------------------------------------------------------------------
# 1. /learn_cmd, /learn, /lc must NOT be registered as builtins
# ---------------------------------------------------------------------------


class TestLearnCmdRemoved:
    """Verify the /learn_cmd compatibility stub is fully gone."""

    def test_learn_cmd_not_in_slash_commands(self) -> None:
        assert "learn_cmd" not in SLASH_COMMANDS

    def test_learn_not_in_slash_commands(self) -> None:
        assert "learn" not in SLASH_COMMANDS

    def test_lc_not_in_slash_commands(self) -> None:
        assert "lc" not in SLASH_COMMANDS


# ---------------------------------------------------------------------------
# 2. /help output must NOT contain hardcoded netops text
# ---------------------------------------------------------------------------

NETOPS_FORBIDDEN = [
    "Domain Commands",
    "learn_cmd",
    "IP location lookup",
    "Device health check",
    "Network summary",
]


class TestHelpNoNetopsText:
    """Verify hardcoded netops references are purged from /help output."""

    @pytest.fixture()
    def help_output(self, tmp_path: Path) -> str:
        """Run /help with an empty workspace so only builtins appear."""
        ws = tmp_path / ".olav" / "workspace"
        ws.mkdir(parents=True)
        with patch("olav.cli.commands.builtin.build_slash_command_registry") as mock_reg:
            # Return only builtins (simulate empty workspace + no entry points)
            mock_reg.return_value = dict(SLASH_COMMANDS)
            return asyncio.run(cmd_help(""))

    @pytest.mark.parametrize("fragment", NETOPS_FORBIDDEN)
    def test_no_netops_text(self, help_output: str, fragment: str) -> None:
        assert fragment not in help_output, f"Hardcoded netops text still present: {fragment!r}"


# ---------------------------------------------------------------------------
# 3. /help dynamically lists commands from the merged registry
# ---------------------------------------------------------------------------


class TestHelpDynamic:
    """Verify /help uses the merged registry to discover commands."""

    @pytest.fixture()
    def fake_workspace_spec(self) -> SlashCommandSpec:
        return SlashCommandSpec(
            name="netsnap",
            kind="shell",
            source="workspace_manifest",
            help="Take a network snapshot",
            aliases=["ns"],
            script="scripts/snap.sh",
        )

    @pytest.fixture()
    def fake_entrypoint_spec(self) -> SlashCommandSpec:
        return SlashCommandSpec(
            name="diagcheck",
            kind="python",
            source="entry_point",
            help="Run diagnostic checks",
            entrypoint="diag.cli:run",
        )

    def _run_help(self, extra_specs: list[SlashCommandSpec] | None = None) -> str:
        """Build a merged registry with builtins + optional extras, run /help."""
        merged: dict = dict(SLASH_COMMANDS)
        for spec in extra_specs or []:
            merged[spec.name] = spec
            for alias in spec.aliases:
                merged[alias] = spec

        with patch(
            "olav.cli.commands.builtin.build_slash_command_registry",
            return_value=merged,
        ):
            return asyncio.run(cmd_help(""))

    def test_builtin_commands_listed(self) -> None:
        output = self._run_help()
        for name in ("help", "clear", "history", "quit", "exit"):
            assert f"/{name}" in output, f"Builtin /{name} missing from /help"

    def test_workspace_command_listed(self, fake_workspace_spec: SlashCommandSpec) -> None:
        output = self._run_help([fake_workspace_spec])
        assert "/netsnap" in output
        assert "Take a network snapshot" in output

    def test_entrypoint_command_listed(self, fake_entrypoint_spec: SlashCommandSpec) -> None:
        output = self._run_help([fake_entrypoint_spec])
        assert "/diagcheck" in output
        assert "Run diagnostic checks" in output

    def test_input_features_section_preserved(self) -> None:
        output = self._run_help()
        assert "@" in output  # @file reference
        assert "!shell" in output or "!" in output
        assert "multi-line" in output.lower() or "Enter twice" in output

    def test_help_specific_command_still_works(self) -> None:
        """``/help clear`` should still show detailed help for that command."""
        with patch(
            "olav.cli.commands.builtin.build_slash_command_registry",
            return_value=dict(SLASH_COMMANDS),
        ):
            output = asyncio.run(cmd_help("clear"))
        assert "clear" in output.lower()

    def test_help_specific_workspace_command(self, fake_workspace_spec: SlashCommandSpec) -> None:
        """``/help netsnap`` should show the spec's help text."""
        merged: dict = dict(SLASH_COMMANDS)
        merged[fake_workspace_spec.name] = fake_workspace_spec
        with patch(
            "olav.cli.commands.builtin.build_slash_command_registry",
            return_value=merged,
        ):
            output = asyncio.run(cmd_help("netsnap"))
        assert "Take a network snapshot" in output

    def test_aliases_not_duplicated_as_separate_commands(
        self, fake_workspace_spec: SlashCommandSpec
    ) -> None:
        """Aliases should not appear as their own top-level command entries."""
        output = self._run_help([fake_workspace_spec])
        # "ns" alias should appear as alias notation, not as a standalone command
        lines = output.split("\n")
        standalone_ns = [
            l for l in lines if l.strip().startswith("/ns ") or l.strip().startswith("/ns\t")
        ]
        assert len(standalone_ns) == 0, "Alias /ns listed as standalone command"

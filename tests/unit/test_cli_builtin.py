"""Unit tests for CLI builtin commands module.

Run: pytest tests/unit/test_cli_builtin.py -v
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


class TestBuiltinCommands:
    """Tests for src/olav/cli/commands/builtin.py"""

    def test_register_command_decorator(self):
        """Test register_command decorator."""
        from src.olav.cli.commands.builtin import register_command, SLASH_COMMANDS

        @register_command("test_cmd")
        def test_func():
            pass

        assert "test_cmd" in SLASH_COMMANDS

    def test_slash_commands_dict(self):
        """Test SLASH_COMMANDS dict exists."""
        from src.olav.cli.commands.builtin import SLASH_COMMANDS

        assert isinstance(SLASH_COMMANDS, dict)

    def test_execute_command_import(self):
        """Test execute_command can be imported."""
        from src.olav.cli.commands.builtin import execute_command

        assert callable(execute_command)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

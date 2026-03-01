"""Unit tests for src/olav/cli/commands/base.py."""

import pytest
from unittest.mock import MagicMock
from src.olav.cli.commands.base import BaseCommand


class TestBaseCommand:
    """Tests for BaseCommand class."""

    def test_init(self):
        """Test BaseCommand initialization."""

        class TestCommand(BaseCommand):
            async def execute(self, args: str = "") -> str:
                return "test"

        cmd = TestCommand("test", "Test command")
        assert cmd.name == "test"
        assert cmd.description == "Test command"
        assert cmd.aliases == []

    def test_parse_args_empty(self):
        """Test parse_args with empty string."""

        class TestCommand(BaseCommand):
            async def execute(self, args: str = "") -> str:
                return "test"

        cmd = TestCommand("test")
        result = cmd.parse_args("")
        assert result == {}

    def test_parse_args_with_args(self):
        """Test parse_args with arguments."""

        class TestCommand(BaseCommand):
            async def execute(self, args: str = "") -> str:
                return "test"

        cmd = TestCommand("test")
        result = cmd.parse_args("arg1 arg2")
        assert result == {"args": ["arg1", "arg2"]}

    def test_format_output_string(self):
        """Test format_output with string."""

        class TestCommand(BaseCommand):
            async def execute(self, args: str = "") -> str:
                return "test"

        cmd = TestCommand("test")
        result = cmd.format_output("hello")
        assert result == "hello"

    def test_format_output_dict(self):
        """Test format_output with dict."""

        class TestCommand(BaseCommand):
            async def execute(self, args: str = "") -> str:
                return "test"

        cmd = TestCommand("test")
        result = cmd.format_output({"key": "value"})
        assert result == "{'key': 'value'}"

    @pytest.mark.asyncio
    async def test_validate_prerequisites(self):
        """Test validate_prerequisites default."""

        class TestCommand(BaseCommand):
            async def execute(self, args: str = "") -> str:
                return "test"

        cmd = TestCommand("test")
        result = await cmd.validate_prerequisites()
        assert result is True

    @pytest.mark.asyncio
    async def test_execute(self):
        """Test execute method."""

        class TestCommand(BaseCommand):
            async def execute(self, args: str = "") -> str:
                return "executed"

        cmd = TestCommand("test")
        result = await cmd.execute("arg")
        assert result == "executed"

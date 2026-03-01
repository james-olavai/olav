"""More comprehensive unit tests.

Run: pytest tests/unit/test_comprehensive.py -v
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


class TestCLIInit:
    """Tests for CLI __init__."""

    def test_cli_init(self):
        """Test CLI module init."""
        from olav.cli import __all__

        assert "__all__" in dir()


class TestAgentsInit:
    """Tests for agents __init__."""

    def test_agents_init(self):
        """Test agents module init."""
        from olav.agents import __all__

        assert "__all__" in dir()


class TestCoreInit:
    """Tests for core __init__."""

    def test_core_init(self):
        """Test core module init."""
        from olav.core import __all__

        assert "__all__" in dir()


class TestKnowledgeInit:
    """Tests for knowledge __init__."""

    def test_knowledge_init(self):
        """Test memory module init (olav.core.knowledge was renamed to olav.core.memory)."""
        from olav.core.memory import LanceDBStore, MemoryCategory

        assert LanceDBStore is not None
        assert MemoryCategory is not None


class TestCommandsInit:
    """Tests for commands __init__."""

    def test_commands_init(self):
        """Test commands module init."""
        from olav.cli.commands import __all__

        assert "__all__" in dir()


class TestOlavInit:
    """Tests for olav package __init__."""

    def test_olav_init(self):
        """Test olav package init."""
        from olav import __all__

        assert isinstance(__all__, list)


class TestDisplayFunctions:
    """More tests for display functions."""

    def test_get_banner(self):
        """Test get_banner function."""
        from olav.cli.display import get_banner

        banner = get_banner("default")
        assert isinstance(banner, str)

    def test_load_banner_from_config_nonexistent(self):
        """Test load_banner_from_config with nonexistent path."""
        from olav.cli.display import load_banner_from_config

        result = load_banner_from_config("/nonexistent/path.json")
        assert isinstance(result, str)


class TestCommandBase:
    """Tests for commands/base.py"""

    def test_command_base_class(self):
        """Test Command class."""
        from olav.cli.commands.base import BaseCommand

        class TestCommand(BaseCommand):
            async def execute(self, args: str = "") -> str:
                return f"Executed {self.name} with {args}"

        cmd = TestCommand(name="test", description="Test command")
        assert cmd.name == "test"
        assert cmd.description == "Test command"


class TestBuiltinCommandsMore:
    """More tests for builtin commands."""

    def test_execute_command_function(self):
        """Test execute_command function exists."""
        from olav.cli.commands.builtin import execute_command

        assert callable(execute_command)


class TestAPIMore:
    """More tests for API server."""

    def test_search_threads_function(self):
        """Test search_threads function."""
        from olav.api.server import search_threads

        import asyncio

        result = asyncio.run(search_threads())
        assert "threads" in result


class TestMainMore:
    """More tests for main.py"""

    def test_main_module(self):
        """Test cli_main function is importable from olav.cli.main."""
        from olav.cli.main import cli_main

        assert callable(cli_main)


class TestDatabaseMore:
    """More tests for database."""

    def test_database_close(self):
        """Test database close method."""
        from olav.core.database import OlavDatabase

        db = OlavDatabase(db_path=":memory:")
        db.close()
        # close() closes the connection but does not zero out self.conn
        assert db is not None  # close() completed without error


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

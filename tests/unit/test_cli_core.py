"""Unit tests for CLI input parser and display module.

Run: pytest tests/unit/test_cli_core.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


class TestInputParser:
    """Tests for src/olav/cli/input_parser.py"""

    def test_expand_file_references_basic(self, tmp_path: Path):
        """Test basic file reference expansion."""
        from olav.cli.input_parser import expand_file_references

        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = expand_file_references("@test.txt", base_dir=tmp_path)
        assert "Hello World" in result
        assert "```txt" in result

    def test_expand_file_references_nonexistent(self):
        """Test handling of nonexistent file references."""
        from olav.cli.input_parser import expand_file_references

        result = expand_file_references("@nonexistent.txt")
        assert "@nonexistent.txt" in result

    def test_expand_file_references_no_base_dir(self, tmp_path: Path):
        """Test file reference without base_dir."""
        from olav.cli.input_parser import expand_file_references

        result = expand_file_references("@/nonexistent/file.txt")
        assert "@/nonexistent/file.txt" in result

    def test_parse_input_shell_command(self):
        """Test parsing shell command."""
        from olav.cli.input_parser import parse_input

        text, is_shell, cmd = parse_input("!ls -la")
        assert is_shell is True
        assert cmd == "ls -la"

    def test_parse_input_regular_text(self):
        """Test parsing regular text."""
        from olav.cli.input_parser import parse_input

        text, is_shell, cmd = parse_input("Show me the devices")
        assert is_shell is False
        assert cmd is None

    def test_parse_input_with_file_reference(self, tmp_path: Path):
        """Test parsing with file reference."""
        from olav.cli.input_parser import parse_input, expand_file_references

        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        text = expand_file_references("Query: @test.txt", base_dir=tmp_path)
        text, is_shell, cmd = parse_input(text)
        assert is_shell is False


class TestDisplay:
    """Tests for src/olav/cli/display.py"""

    def test_display_import(self):
        """Test display module can be imported."""
        from olav.cli import display
        assert display is not None

    def test_display_banner(self):
        """Test display_banner function."""
        from olav.cli.display import display_banner
        mock_console = MagicMock()
        display_banner("Test", console=mock_console)
        mock_console.print.assert_called()

    def test_streaming_display_init(self):
        """Test StreamingDisplay init."""
        from olav.cli.display import StreamingDisplay
        sd = StreamingDisplay(verbose=True)
        assert sd.verbose is True

    def test_streaming_display_thinking(self):
        """Test show_thinking."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console, verbose=True)
        sd.show_thinking("Thinking...")
        mock_console.print.assert_called()

    def test_streaming_display_result(self):
        """Test show_result."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console)
        sd.show_result("Result")
        mock_console.print.assert_called()

    def test_streaming_display_error(self):
        """Test show_error."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console)
        sd.show_error("Error")
        mock_console.print.assert_called()

    def test_streaming_display_tool_call(self):
        """Test show_tool_call."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console)
        sd.show_tool_call("test_tool", device="R1", command="show version")
        mock_console.print.assert_called()

    def test_streaming_display_tool_compact(self):
        """Test show_tool_compact."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console)
        sd.show_tool_compact("test_tool", detail="detail")
        mock_console.print.assert_called()

    def test_streaming_display_quiet(self):
        """Test StreamingDisplay quiet mode - tool calls suppressed."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console, quiet=True)
        sd.show_tool_call("test_tool")
        # Tool calls suppressed in quiet mode
        mock_console.print.assert_not_called()

    def test_streaming_display_data_source_sql(self):
        """Test StreamingDisplay quiet mode - tool calls suppressed."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console, quiet=True)
        sd.show_tool_call("test_tool")
        # Tool calls suppressed in quiet mode
        mock_console.print.assert_not_called()
        """Test StreamingDisplay in quiet mode - tool calls suppressed."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console, quiet=True)
        sd.show_tool_call("test_tool")
        # Tool calls should be suppressed in quiet mode
        mock_console.print.assert_not_called()
        """Test StreamingDisplay in quiet mode."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console, quiet=True)
        sd.show_tool_call("test_tool")
        sd.show_result("Result")
        # Should not print in quiet mode
        mock_console.print.assert_not_called()

    def test_streaming_display_data_source_sql(self):
        """Test show_data_source_indicator for SQL."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console)
        sd.show_data_source_indicator("sql", snapshot_time="2024-01-01")
        mock_console.print.assert_called()

    def test_streaming_display_data_source_cli(self):
        """Test show_data_source_indicator for CLI."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console)
        sd.show_data_source_indicator("cli", device="R1")
        mock_console.print.assert_called()
        """Test show_error."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console)
        sd.show_error("Error")
        mock_console.print.assert_called()

    def test_display_todos(self):
        """Test display_todos."""
        from olav.cli.display import display_todos
        mock_graph = MagicMock()
        mock_state = MagicMock()
        mock_state.values = {"todos": [{"id": 1, "status": "done", "title": "Test"}]}
        mock_graph.get_state.return_value = mock_state
        mock_console = MagicMock()
        display_todos(mock_graph, console=mock_console)
        mock_console.print.assert_called()

    def test_display_todos_no_state(self):
        """Test display_todos with no state."""
        from olav.cli.display import display_todos
        mock_graph = MagicMock()
        mock_graph.get_state.return_value = None
        mock_console = MagicMock()
        # Should not raise
        display_todos(mock_graph, console=mock_console)

    def test_print_error(self):
        """Test print_error."""
        from olav.cli.display import print_error
        with patch("olav.cli.display.RICH_AVAILABLE", True):
            with patch("olav.cli.display.Console") as mock_cls:
                mock_console = MagicMock()
                mock_cls.return_value = mock_console
                print_error("Error")
                mock_console.print.assert_called()

    def test_print_success(self):
        """Test print_success."""
        from olav.cli.display import print_success
        with patch("olav.cli.display.RICH_AVAILABLE", True):
            with patch("olav.cli.display.Console") as mock_cls:
                mock_console = MagicMock()
                mock_cls.return_value = mock_console
                print_success("Success")
                mock_console.print.assert_called()

    def test_print_welcome(self):
        """Test print_welcome."""
        from olav.cli.display import print_welcome
        with patch("olav.cli.display.RICH_AVAILABLE", True):
            with patch("olav.cli.display.Console") as mock_cls:
                mock_console = MagicMock()
                mock_cls.return_value = mock_console
                print_welcome("Welcome")
                mock_console.print.assert_called()

    def test_format_and_print_invalid_key(self):
        """Test _format_and_print with invalid format key."""
        from olav.cli.display import _format_and_print
        with pytest.raises(ValueError):
            _format_and_print("test", "invalid_key")

    def test_load_banner_from_config(self):
        """Test load_banner_from_config."""
        from olav.cli.display import load_banner_from_config
        with patch("olav.cli.display.get_banner", return_value="Banner"):
            result = load_banner_from_config("/fake/path")
            assert result == "Banner"

    def test_streaming_display_processing_status(self):
        """Test show_processing_status."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console, show_spinner=False)
        sd.show_processing_status("Working...")
        mock_console.print.assert_called()

    def test_streaming_display_stop_status(self):
        """Test stop_processing_status."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console)
        sd.stop_processing_status()
        # Should not raise

    def test_streaming_display_processing_status_quiet(self):
        """Test show_processing_status in quiet mode."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console, quiet=True)
        sd.show_processing_status("Working...")
        mock_console.print.assert_not_called()

    def test_load_banner_from_config(self):
        """Test show_processing_status in quiet mode."""
        from olav.cli.display import StreamingDisplay
        mock_console = MagicMock()
        sd = StreamingDisplay(console=mock_console, quiet=True)
        sd.show_processing_status("Working...")
        mock_console.print.assert_not_called()
        """Test print_success."""
        from olav.cli.display import print_success
        with patch("olav.cli.display.RICH_AVAILABLE", True):
            with patch("olav.cli.display.Console") as mock_cls:
                mock_console = MagicMock()
                mock_cls.return_value = mock_console
                print_success("Success")
                mock_console.print.assert_called()

    def test_load_banner_from_config(self):
        """Test load_banner_from_config."""
        from olav.cli.display import load_banner_from_config
        with patch("olav.cli.display.get_banner", return_value="Banner"):
            result = load_banner_from_config("/fake/path")
            assert result == "Banner"
        """Test display_todos."""
        from olav.cli.display import display_todos
        mock_graph = MagicMock()
        mock_state = MagicMock()
        mock_state.values = {"todos": [{"id": 1, "status": "done", "title": "Test"}]}
        mock_graph.get_state.return_value = mock_state
        mock_console = MagicMock()
        display_todos(mock_graph, console=mock_console)
        mock_console.print.assert_called()
    """Tests for src/olav/cli/display.py"""

    def test_display_import(self):
        """Test display module can be imported."""
        from olav.cli import display

        assert display is not None


class TestCommands:
    """Tests for src/olav/cli/commands/"""

    def test_commands_base_import(self):
        """Test commands base module can be imported."""
        from olav.cli.commands import base

        assert base is not None

    def test_commands_builtin_import(self):
        """Test commands builtin module can be imported."""
        from olav.cli.commands import builtin

        assert builtin is not None


class TestAPI:
    """Tests for src/olav/api/"""

    def test_api_server_import(self):
        """Test API server module can be imported."""
        from olav.api import server

        assert server is not None

    def test_api_init(self):
        """Test API __init__."""
        from olav.api import server

        assert server is not None


class TestCoreModule:
    """Tests for src/olav/core/ modules"""

    def test_core_database_import(self):
        """Test database module can be imported."""
        from olav.core import database

        assert database is not None

    def test_core_llm_import(self):
        """Test llm module can be imported."""
        from olav.core import llm

        assert llm is not None

    def test_core_tool_discovery_import(self):
        """Test tool_discovery module can be imported."""
        from olav.core import tool_discovery

        assert tool_discovery is not None

    def test_core_command_registry_import(self):
        """Test command_registry module can be imported."""
        from olav.core import command_registry

        assert command_registry is not None


class TestKnowledgeModule:
    """Tests for olav.core.memory (formerly olav.core.knowledge)."""

    def test_knowledge_text_processor_import(self):
        """Memory module must be importable (knowledge was renamed to memory)."""
        from olav.core import memory

        assert memory is not None

    def test_knowledge_embedding_gateway_import(self):
        """LanceDB store must be importable as the embedding-backed memory store."""
        from olav.core.memory import LanceDBStore

        assert LanceDBStore is not None


class TestAgentsModule:
    """Tests for src/olav/agents/ modules"""

    def test_agents_agent_import(self):
        """Test agent module can be imported."""
        from olav.agents import agent

        assert agent is not None


class TestMainModule:
    """Tests for src/olav/main.py"""

    def test_main_import(self):
        """Test main function is importable from olav.cli.main."""
        from olav.cli.main import cli_main

        assert callable(cli_main)


class TestOlavPackage:
    """Tests for src/olav/__init__.py"""

    def test_olav_package_import(self):
        """Test olav package can be imported."""
        from olav import __version__

        assert __version__ is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

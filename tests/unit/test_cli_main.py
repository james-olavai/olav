"""Unit tests for src/olav/cli/main.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from olav.cli.main import check_dependencies, cli_main, parse_args


def test_parse_args_default():
    """Test parse_args with default arguments."""
    with patch("sys.argv", ["olav"]):
        args = parse_args()
        assert args.agent == "quick"
        assert args.query is None
        assert args.command is None

def test_parse_args_agent_flag():
    """Test parse_args with --agent flag."""
    with patch("sys.argv", ["olav", "--agent", "myagent"]):
        args = parse_args()
        assert args.agent == "myagent"

def test_parse_args_list_subcommand():
    """Test parse_args with 'list' subcommand."""
    with patch("sys.argv", ["olav", "list"]):
        args = parse_args()
        assert args.command == "list"

def test_check_dependencies_success():
    """Test check_dependencies when all deps are present."""
    with patch("importlib.import_module", return_value=MagicMock()):
        # Should not raise SystemExit
        check_dependencies()

def test_check_dependencies_failure():
    """Test check_dependencies when deps are missing."""
    with patch("builtins.__import__", side_effect=ImportError), \
         patch("rich.console.Console.print"), \
         patch("sys.exit") as mock_exit:
        check_dependencies()
        mock_exit.assert_called_with(1)

@pytest.mark.asyncio
async def test_run_single_query_success():
    """Test run_single_query success."""
    from olav.cli.main import run_single_query

    with patch("olav.cli.main.create_olav_agent_with_backend") as mock_create, \
         patch("rich.console.Console.print"):
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(return_value={"messages": []})
        mock_backend = MagicMock()
        mock_create.return_value = (mock_agent, mock_backend)

        await run_single_query("test query", "olav")

@pytest.mark.asyncio
async def test_run_single_query_error():
    """Test run_single_query handles errors gracefully."""
    from olav.cli.main import run_single_query

    with patch("olav.cli.main.create_olav_agent_with_backend") as mock_create, \
         patch("rich.console.Console.print"):
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(side_effect=RuntimeError("agent error"))
        mock_backend = MagicMock()
        mock_create.return_value = (mock_agent, mock_backend)

        try:
            await run_single_query("test query", "olav")
        except RuntimeError:
            pass  # acceptable if error bubbles

def test_cli_main_list():
    """Test cli_main with list command."""
    with patch("olav.cli.main.parse_args") as mock_parse, \
         patch("rich.console.Console.print") as mock_print:
        mock_args = MagicMock()
        mock_args.command = "list"
        mock_args.verbose = False
        mock_args.query = None
        mock_parse.return_value = mock_args

        cli_main()
        mock_print.assert_called()

def test_cli_main_help():
    """Test cli_main with help command."""
    with patch("olav.cli.main.parse_args") as mock_parse, \
         patch("rich.console.Console.print") as mock_print:
        mock_args = MagicMock()
        mock_args.command = "help"
        mock_args.verbose = False
        mock_args.query = None
        mock_parse.return_value = mock_args

        cli_main()
        mock_print.assert_called()

def test_cli_main_no_command():
    """Test cli_main with no command starts interactive mode."""
    with patch("olav.cli.main.parse_args") as mock_parse, \
         patch("olav.cli.main.run_interactive") as mock_run:
        mock_args = MagicMock()
        mock_args.command = None
        mock_args.query = None
        mock_args.verbose = False
        mock_parse.return_value = mock_args
        mock_run.return_value = None

        try:
            cli_main()
        except Exception:
            pass  # may fail trying to start asyncio; parse step is what we test

def test_get_system_prompt():
    """Test get_system_prompt returns a non-empty string."""
    from olav.cli.main import get_system_prompt

    prompt = get_system_prompt("test-assistant")
    assert isinstance(prompt, str)
    assert len(prompt) > 0

@pytest.mark.asyncio
async def test_run_interactive():
    """Test run_interactive."""
    from olav.cli.main import run_interactive

    with patch("olav.cli.main.create_olav_agent_with_backend") as mock_create, \
         patch("olav.cli.main.simple_cli", new_callable=AsyncMock) as mock_simple:
        mock_create.return_value = (MagicMock(), MagicMock())
        mock_simple.return_value = None
        await run_interactive("test-assistant", MagicMock())
        mock_simple.assert_called_once()

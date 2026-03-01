"""Unit tests for src/olav/cli/commands/builtin.py."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from olav.cli.commands.builtin import (
    SLASH_COMMANDS,
    register_command,
    execute_command,
    cmd_help,
    cmd_clear,
    cmd_history,
    cmd_quit,
    cmd_exit,
    cmd_learn,
    cmd_config,
)


@pytest.mark.asyncio
async def test_execute_command_help():
    """Test executing /help command."""
    result = await execute_command("/help")
    assert "OLAV CLI - Available Commands" in result


@pytest.mark.asyncio
async def test_execute_command_unknown():
    """Test executing unknown command."""
    result = await execute_command("/unknown")
    assert "Unknown command: /unknown" in result


@pytest.mark.asyncio
async def test_execute_command_not_slash():
    """Test executing non-slash command."""
    with pytest.raises(ValueError):
        await execute_command("help")


@pytest.mark.asyncio
async def test_cmd_help_specific():
    """Test /help <command>."""
    result = await cmd_help("clear")
    assert "Help for /clear" in result
    assert "Clear conversation memory" in result


@pytest.mark.asyncio
async def test_cmd_clear():
    """Test /clear command."""
    result = await cmd_clear("")
    assert "Conversation memory cleared" in result


@pytest.mark.asyncio
async def test_cmd_history():
    """Test /history command."""
    result = await cmd_history("")
    assert "Recent Command History" in result or "Session History" in result


@pytest.mark.asyncio
async def test_cmd_quit():
    """Test /quit command."""
    with pytest.raises(EOFError):
        await cmd_quit("")


@pytest.mark.asyncio
async def test_cmd_learn_no_args():
    """Test /learn_cmd without args."""
    result = await cmd_learn("")
    assert "Usage: /learn_cmd" in result


@pytest.mark.asyncio
async def test_cmd_learn_success():
    """Test /learn_cmd success."""
    with patch("olav.agents.agent.create_olav_agent") as mock_create:
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(return_value="Learned successfully")
        mock_create.return_value = mock_agent

        result = await cmd_learn('"show version" --device R1')
        assert result == "Learned successfully"
        mock_agent.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_config_no_args():
    """Test /config without args."""
    result = await cmd_config("")
    assert "Usage: /config" in result


@pytest.mark.asyncio
async def test_cmd_config_success():
    """Test /config success."""
    with patch("olav.agents.agent.create_olav_agent") as mock_create:
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(return_value="Configured successfully")
        mock_create.return_value = mock_agent

        result = await cmd_config("backup database")
        assert result == "Configured successfully"
        mock_agent.ainvoke.assert_called_once()
@pytest.mark.asyncio
async def test_register_command():
    """Test register_command decorator."""
    @register_command("test_cmd")
    async def test_func(args):
        return "test"
    
    assert "test_cmd" in SLASH_COMMANDS
    assert SLASH_COMMANDS["test_cmd"] == test_func
    
    # Clean up
    del SLASH_COMMANDS["test_cmd"]


@pytest.mark.asyncio
async def test_execute_command_exception():
    """Test execute_command generic exception handling."""
    # Mock a command that raises an exception
    mock_func = MagicMock(side_effect=Exception("Test error"))
    SLASH_COMMANDS["error_cmd"] = mock_func
    
    result = await execute_command("/error_cmd")
    assert "Error executing /error_cmd: Test error" in result
    
    # Clean up
    del SLASH_COMMANDS["error_cmd"]


@pytest.mark.asyncio
async def test_cmd_help_unknown():
    """Test /help <unknown_command>."""
    result = await cmd_help("unknown_cmd")
    assert "Unknown command: /unknown_cmd" in result


@pytest.mark.asyncio
async def test_cmd_exit():
    """Test /exit command."""
    with pytest.raises(EOFError):
        await cmd_exit("")


@pytest.mark.asyncio
async def test_cmd_learn_arg_parsing_errors():
    """Test /learn_cmd argument parsing errors."""
    # Test invalid shlex splitting
    result = await cmd_learn('"unclosed quote')
    assert "Error parsing arguments" in result

    # Test missing device value
    result = await cmd_learn('"show version" --device')
    assert "--device requires a value" in result

    # Test missing platform value
    result = await cmd_learn('"show version" --device R1 --platform')
    assert "--platform requires a value" in result

    # Test invalid timeout (non-integer)
    result = await cmd_learn('"show version" --device R1 --timeout abc')
    assert "--timeout must be an integer" in result

    # Test missing timeout value
    result = await cmd_learn('"show version" --device R1 --timeout')
    assert "--timeout requires a value" in result

    # Test missing command
    result = await cmd_learn('--device R1')
    assert "Command is required" in result

    # Test missing device (but command present)
    result = await cmd_learn('"show version"')
    assert "Device is required (--device)" in result


@pytest.mark.asyncio
async def test_cmd_learn_exception():
    """Test /learn_cmd exception handling."""
    with patch("olav.agents.agent.create_olav_agent") as mock_create:
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(side_effect=Exception("Agent error"))
        mock_create.return_value = mock_agent

        result = await cmd_learn('"show version" --device R1')
        assert "Error: Agent error" in result


@pytest.mark.asyncio
async def test_cmd_config_exception():
    """Test /config exception handling."""
    with patch("olav.agents.agent.create_olav_agent") as mock_create:
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(side_effect=Exception("Config error"))
        mock_create.return_value = mock_agent

        result = await cmd_config("backup database")
        assert "Config Error: Config error" in result

@pytest.mark.asyncio
async def test_execute_command_quit():
    """Test execute_command with /quit (EOFError)."""
    with pytest.raises(EOFError):
        await execute_command("/quit")


@pytest.mark.asyncio
async def test_cmd_learn_full_args():
    """Test /learn_cmd with all arguments."""
    with patch("olav.agents.agent.create_olav_agent") as mock_create:
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(return_value="Learned successfully")
        mock_create.return_value = mock_agent

        result = await cmd_learn('"show version" --device R1 --platform cisco_ios --timeout 30')
        assert result == "Learned successfully"
        
        # Verify arguments were passed correctly
        args, kwargs = mock_agent.ainvoke.call_args
        query = args[0]
        assert "Learn command: show version" in query
        assert "Device: R1" in query
        assert "Platform: cisco_ios" in query
        assert "Timeout: 30s" in query


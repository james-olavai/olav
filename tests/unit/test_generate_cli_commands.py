"""
Unit tests for generate_cli_commands tool in cli_tool.py.

Tests LLM-based command generation with NetBox platform resolution.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from olav.tools.cli_tool import generate_cli_commands


class TestGenerateCLICommands:
    """Tests for generate_cli_commands tool function."""

    @pytest.mark.asyncio
    async def test_missing_platform_and_device(self):
        """Test error when neither platform nor device provided."""
        result = await generate_cli_commands.ainvoke({
            "intent": "show bgp status",
        })

        assert result["commands"] == []
        assert "error" in result
        assert "Missing platform" in result["error"]

    @pytest.mark.asyncio
    async def test_explicit_platform(self):
        """Test with explicit platform parameter."""
        with patch("olav.tools.cli_tool.TemplateManager") as mock_tm:
            mock_instance = MagicMock()
            mock_instance.get_commands_for_platform.return_value = [
                ("show ip bgp summary", None, False),
                ("show ip bgp neighbors", None, False),
            ]
            mock_tm.return_value = mock_instance

            with patch("olav.tools.cli_command_generator.generate_platform_command") as mock_gen:
                mock_gen.return_value = {
                    "commands": ["show ip bgp summary"],
                    "explanation": "Shows BGP summary",
                    "warnings": [],
                    "alternatives": ["show bgp all summary"],
                    "cached": False,
                }

                result = await generate_cli_commands.ainvoke({
                    "intent": "show bgp status",
                    "platform": "cisco_ios",
                })

                assert result["commands"] == ["show ip bgp summary"]
                assert result["platform"] == "cisco_ios"
                mock_gen.assert_called_once()

    @pytest.mark.asyncio
    async def test_device_with_netbox_platform(self):
        """Test platform resolution from NetBox device."""
        with patch("olav.tools.cli_tool.get_device_platform_from_netbox") as mock_netbox:
            mock_netbox.return_value = "cisco-ios"  # NetBox uses hyphens

            with patch("olav.tools.cli_tool.TemplateManager") as mock_tm:
                mock_instance = MagicMock()
                mock_instance.get_commands_for_platform.return_value = []
                mock_tm.return_value = mock_instance

                with patch("olav.tools.cli_command_generator.generate_platform_command") as mock_gen:
                    mock_gen.return_value = {
                        "commands": ["show version"],
                        "explanation": "Shows version",
                        "warnings": [],
                        "alternatives": [],
                        "cached": False,
                    }

                    result = await generate_cli_commands.ainvoke({
                        "intent": "show device version",
                        "device": "R1",
                    })

                    assert result["platform"] == "cisco_ios"  # Normalized
                    mock_netbox.assert_called_once_with("R1")

    @pytest.mark.asyncio
    async def test_device_netbox_fallback_to_platform(self):
        """Test fallback to explicit platform when NetBox fails."""
        with patch("olav.tools.cli_tool.get_device_platform_from_netbox") as mock_netbox:
            mock_netbox.return_value = None  # NetBox query fails

            with patch("olav.tools.cli_tool.TemplateManager") as mock_tm:
                mock_instance = MagicMock()
                mock_instance.get_commands_for_platform.return_value = []
                mock_tm.return_value = mock_instance

                with patch("olav.tools.cli_command_generator.generate_platform_command") as mock_gen:
                    mock_gen.return_value = {
                        "commands": ["show bgp summary"],
                        "explanation": "",
                        "warnings": [],
                        "alternatives": [],
                        "cached": False,
                    }

                    result = await generate_cli_commands.ainvoke({
                        "intent": "show bgp",
                        "device": "R1",
                        "platform": "juniper_junos",  # Fallback
                    })

                    assert result["platform"] == "juniper_junos"

    @pytest.mark.asyncio
    async def test_passes_context(self):
        """Test context is passed to generator."""
        with patch("olav.tools.cli_tool.TemplateManager") as mock_tm:
            mock_instance = MagicMock()
            mock_instance.get_commands_for_platform.return_value = []
            mock_tm.return_value = mock_instance

            with patch("olav.tools.cli_command_generator.generate_platform_command") as mock_gen:
                mock_gen.return_value = {
                    "commands": [],
                    "explanation": "",
                    "warnings": [],
                    "alternatives": [],
                    "cached": False,
                }

                await generate_cli_commands.ainvoke({
                    "intent": "check interfaces",
                    "platform": "arista_eos",
                    "context": "device is spine switch",
                })

                # Verify context was passed
                call_kwargs = mock_gen.call_args.kwargs
                assert call_kwargs["context"] == "device is spine switch"

    @pytest.mark.asyncio
    async def test_limits_available_commands(self):
        """Test available commands are limited to 50."""
        with patch("olav.tools.cli_tool.TemplateManager") as mock_tm:
            mock_instance = MagicMock()
            # Return 100 commands
            mock_instance.get_commands_for_platform.return_value = [
                (f"show cmd{i}", None, False) for i in range(100)
            ]
            mock_tm.return_value = mock_instance

            with patch("olav.tools.cli_command_generator.generate_platform_command") as mock_gen:
                mock_gen.return_value = {
                    "commands": [],
                    "explanation": "",
                    "warnings": [],
                    "alternatives": [],
                    "cached": False,
                }

                await generate_cli_commands.ainvoke({
                    "intent": "test",
                    "platform": "cisco_ios",
                })

                # Verify only 50 commands passed
                call_kwargs = mock_gen.call_args.kwargs
                assert len(call_kwargs["available_commands"]) == 50

    @pytest.mark.asyncio
    async def test_result_includes_cached_flag(self):
        """Test result includes cached flag from generator."""
        with patch("olav.tools.cli_tool.TemplateManager") as mock_tm:
            mock_instance = MagicMock()
            mock_instance.get_commands_for_platform.return_value = []
            mock_tm.return_value = mock_instance

            with patch("olav.tools.cli_command_generator.generate_platform_command") as mock_gen:
                mock_gen.return_value = {
                    "commands": ["show version"],
                    "explanation": "test",
                    "warnings": [],
                    "alternatives": [],
                    "cached": True,  # From cache
                }

                result = await generate_cli_commands.ainvoke({
                    "intent": "show version",
                    "platform": "cisco_ios",
                })

                assert result["cached"] is True

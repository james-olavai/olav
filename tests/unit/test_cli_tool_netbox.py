"""
Tests for CLI Tool NetBox Integration (Phase B.1 Step 3).

Tests NetBox platform injection functionality where device.platform
is queried from NetBox SSOT instead of hardcoding platform strings.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from olav.tools.cli_tool import (
    CLITemplateTool,
    get_device_platform_from_netbox,
    _normalize_platform_slug
)


class TestNetBoxPlatformHelpers:
    """Test NetBox platform helper functions."""
    
    def test_normalize_platform_slug_cisco_ios(self):
        """Test normalization of cisco-ios slug."""
        assert _normalize_platform_slug("cisco-ios") == "cisco_ios"
    
    def test_normalize_platform_slug_arista_eos(self):
        """Test normalization of arista-eos slug."""
        assert _normalize_platform_slug("arista-eos") == "arista_eos"
    
    def test_normalize_platform_slug_cisco_iosxr(self):
        """Test normalization of cisco-iosxr slug."""
        assert _normalize_platform_slug("cisco-iosxr") == "cisco_iosxr"
    
    @patch("olav.tools.cli_tool.netbox_api_call")
    def test_get_device_platform_success(self, mock_api):
        """Test successful device platform query."""
        mock_api.return_value = {
            "results": [
                {
                    "id": 1,
                    "name": "R1",
                    "platform": {
                        "id": 2,
                        "name": "Cisco IOS",
                        "slug": "cisco-ios"
                    }
                }
            ]
        }
        
        result = get_device_platform_from_netbox("R1")
        assert result == "cisco-ios"
        mock_api.assert_called_once_with(
            path="/dcim/devices/",
            method="GET",
            params={"name": "R1"}
        )
    
    @patch("olav.tools.cli_tool.netbox_api_call")
    def test_get_device_platform_not_found(self, mock_api):
        """Test device not found in NetBox."""
        mock_api.return_value = {"results": []}
        
        result = get_device_platform_from_netbox("Unknown-Device")
        assert result is None
    
    @patch("olav.tools.cli_tool.netbox_api_call")
    def test_get_device_platform_no_platform_assigned(self, mock_api):
        """Test device with no platform assigned."""
        mock_api.return_value = {
            "results": [
                {
                    "id": 1,
                    "name": "R2",
                    "platform": None
                }
            ]
        }
        
        result = get_device_platform_from_netbox("R2")
        assert result is None
    
    @patch("olav.tools.cli_tool.netbox_api_call")
    def test_get_device_platform_api_error(self, mock_api):
        """Test NetBox API error handling."""
        mock_api.return_value = {
            "status": "error",
            "message": "Connection timeout"
        }
        
        result = get_device_platform_from_netbox("R1")
        assert result is None


class TestCLITemplateToolNetBoxIntegration:
    """Test CLITemplateTool with NetBox platform injection."""
    
    @pytest.fixture
    def temp_templates(self, tmp_path: Path):
        """Create temporary template directory with test templates."""
        tdir = tmp_path / "templates"
        tdir.mkdir()
        (tdir / "cisco_ios_show_version.textfsm").write_text("Value VERSION (.+)")
        (tdir / "cisco_ios_show_ip_interface_brief.textfsm").write_text("Value INTERFACE (.+)")
        return tdir
    
    @pytest.fixture
    def tool(self, temp_templates: Path):
        """Create CLITemplateTool with test templates."""
        return CLITemplateTool(templates_dir=temp_templates)
    
    @pytest.mark.asyncio
    @patch("olav.tools.cli_tool.get_device_platform_from_netbox")
    async def test_execute_with_device_netbox_success(self, mock_netbox, tool):
        """Test execute with device parameter and successful NetBox query."""
        # Mock NetBox returning cisco-ios slug
        mock_netbox.return_value = "cisco-ios"
        
        result = await tool.execute(device="R1", list_all=True)
        
        # Should query NetBox for R1
        mock_netbox.assert_called_once_with("R1")
        
        # Should normalize cisco-ios -> cisco_ios
        assert not result.error
        assert result.metadata["platform"] == "cisco_ios"
        assert result.metadata["platform_source"] == "netbox"
        assert result.metadata["device"] == "R1"
        assert result.device == "R1"
        assert len(result.data) > 0  # Should have templates or fallback
    
    @pytest.mark.asyncio
    @patch("olav.tools.cli_tool.get_device_platform_from_netbox")
    async def test_execute_with_device_netbox_fallback_to_platform(self, mock_netbox, tool):
        """Test fallback to platform parameter when NetBox query fails."""
        # Mock NetBox query failure
        mock_netbox.return_value = None
        
        result = await tool.execute(device="R1", platform="cisco_ios", list_all=True)
        
        # Should try NetBox first
        mock_netbox.assert_called_once_with("R1")
        
        # Should fallback to platform parameter
        assert not result.error
        assert result.metadata["platform"] == "cisco_ios"
        assert result.metadata["platform_source"] == "explicit"
        assert len(result.data) > 0
    
    @pytest.mark.asyncio
    @patch("olav.tools.cli_tool.get_device_platform_from_netbox")
    async def test_execute_with_device_no_fallback_error(self, mock_netbox, tool):
        """Test error when NetBox fails and no platform parameter."""
        # Mock NetBox query failure
        mock_netbox.return_value = None
        
        result = await tool.execute(device="R1", list_all=True)
        
        # Should try NetBox
        mock_netbox.assert_called_once_with("R1")
        
        # Should return error
        assert result.error == "Missing platform parameter"
        assert result.data[0]["status"] == "PARAM_ERROR"
    
    @pytest.mark.asyncio
    async def test_execute_explicit_platform_no_netbox_query(self, tool):
        """Test explicit platform parameter skips NetBox query."""
        with patch("olav.tools.cli_tool.get_device_platform_from_netbox") as mock_netbox:
            result = await tool.execute(platform="cisco_ios", list_all=True)
            
            # Should NOT query NetBox
            mock_netbox.assert_not_called()
            
            # Should use explicit platform
            assert not result.error
            assert result.metadata["platform"] == "cisco_ios"
            assert result.metadata["platform_source"] == "explicit"
    
    @pytest.mark.asyncio
    @patch("olav.tools.cli_tool.get_device_platform_from_netbox")
    async def test_execute_command_lookup_with_netbox(self, mock_netbox, tool):
        """Test command lookup with NetBox platform resolution."""
        mock_netbox.return_value = "cisco-ios"
        
        result = await tool.execute(device="R1", command="show version")
        
        # Should resolve platform from NetBox
        assert result.metadata["platform"] == "cisco_ios"
        assert result.metadata["platform_source"] == "netbox"
        
        # Should find template
        assert not result.error
        assert result.data[0]["command"] == "show version"
        assert result.data[0]["available"] is True
    
    @pytest.mark.asyncio
    @patch("olav.tools.cli_tool.get_device_platform_from_netbox")
    async def test_execute_netbox_platform_priority(self, mock_netbox, tool):
        """Test that device/NetBox platform takes priority over explicit platform."""
        # NetBox returns arista-eos
        mock_netbox.return_value = "arista-eos"
        
        # Provide both device and platform (device should win)
        result = await tool.execute(device="SW1", platform="cisco_ios", list_all=True)
        
        # Should use NetBox platform (arista-eos), not explicit (cisco_ios)
        assert result.metadata["platform"] == "arista_eos"
        assert result.metadata["platform_source"] == "netbox"
        assert result.metadata["device"] == "SW1"

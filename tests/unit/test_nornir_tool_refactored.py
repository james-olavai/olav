"""
Unit tests for refactored Nornir tools (BaseTool + Adapters).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from olav.tools.nornir_tool_refactored import NetconfTool, CLITool
from olav.tools.base import ToolOutput


# Mock ExecutionResult for NornirSandbox
@dataclass
class MockExecutionResult:
    success: bool
    output: str
    error: str = None
    metadata: dict = None


class TestNetconfTool:
    """Test NetconfTool BaseTool implementation."""
    
    @pytest.fixture
    def mock_sandbox(self):
        """Create mock NornirSandbox."""
        sandbox = MagicMock()
        sandbox.execute = AsyncMock()
        return sandbox
    
    @pytest.fixture
    def netconf_tool(self, mock_sandbox):
        """Create NetconfTool with mock sandbox."""
        return NetconfTool(sandbox=mock_sandbox)
    
    def test_initialization(self, netconf_tool):
        """Test tool initialization."""
        assert netconf_tool.name == "netconf_execute"
        assert "NETCONF" in netconf_tool.description
        assert "HITL" in netconf_tool.description
    
    def test_lazy_sandbox_loading(self):
        """Test sandbox is lazy-loaded."""
        tool = NetconfTool(sandbox=None)
        
        # Should not raise exception
        assert tool._sandbox is None
        
        # Access should trigger lazy load
        with patch("olav.tools.nornir_tool_refactored.NornirSandbox") as mock_class:
            mock_instance = MagicMock()
            mock_class.return_value = mock_instance
            
            sandbox = tool.sandbox
            
            mock_class.assert_called_once()
            assert tool._sandbox == mock_instance
    
    @pytest.mark.asyncio
    async def test_execute_get_config_missing_xpath(self, netconf_tool):
        """Test get-config without xpath returns error."""
        result = await netconf_tool.execute(
            device="R1",
            operation="get-config"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.source == "netconf"
        assert result.device == "R1"
        assert result.error is not None
        assert "xpath" in result.error.lower()
        assert result.data[0]["status"] == "PARAM_ERROR"
    
    @pytest.mark.asyncio
    async def test_execute_edit_config_missing_payload(self, netconf_tool):
        """Test edit-config without payload returns error."""
        result = await netconf_tool.execute(
            device="R1",
            operation="edit-config"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.source == "netconf"
        assert result.error is not None
        assert "payload" in result.error.lower()
        assert result.data[0]["status"] == "PARAM_ERROR"
    
    @pytest.mark.asyncio
    async def test_execute_unsupported_operation(self, netconf_tool):
        """Test unsupported operation returns error."""
        result = await netconf_tool.execute(
            device="R1",
            operation="delete-config"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert "unsupported" in result.error.lower()
        assert result.data[0]["status"] == "PARAM_ERROR"
    
    @pytest.mark.asyncio
    async def test_execute_get_config_success(self, netconf_tool, mock_sandbox):
        """Test successful get-config execution."""
        # Mock successful response
        mock_sandbox.execute.return_value = MockExecutionResult(
            success=True,
            output="<interfaces><interface><name>eth0</name><state>up</state></interface></interfaces>",
            error=None
        )
        
        result = await netconf_tool.execute(
            device="R1",
            operation="get-config",
            xpath="/interfaces/interface/state"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.source == "netconf"
        assert result.device == "R1"
        assert result.metadata["operation"] == "get-config"
        assert result.metadata["requires_approval"] is False
        assert "elapsed_ms" in result.metadata
        
        # Verify RPC construction
        mock_sandbox.execute.assert_called_once()
        call_kwargs = mock_sandbox.execute.call_args.kwargs
        assert call_kwargs["device"] == "R1"
        assert call_kwargs["requires_approval"] is False
        assert "<get-config>" in call_kwargs["command"]
        assert "/interfaces/interface/state" in call_kwargs["command"]
    
    @pytest.mark.asyncio
    async def test_execute_edit_config_success(self, netconf_tool, mock_sandbox):
        """Test successful edit-config execution (triggers HITL)."""
        mock_sandbox.execute.return_value = MockExecutionResult(
            success=True,
            output="<ok/>",
            error=None
        )
        
        payload = "<interfaces><interface><name>eth0</name><mtu>9000</mtu></interface></interfaces>"
        
        result = await netconf_tool.execute(
            device="R1",
            operation="edit-config",
            payload=payload
        )
        
        assert isinstance(result, ToolOutput)
        assert result.source == "netconf"
        assert result.metadata["operation"] == "edit-config"
        assert result.metadata["requires_approval"] is True  # HITL flag
        
        # Verify RPC construction
        call_kwargs = mock_sandbox.execute.call_args.kwargs
        assert call_kwargs["requires_approval"] is True
        assert "<edit-config>" in call_kwargs["command"]
        assert payload in call_kwargs["command"]
    
    @pytest.mark.asyncio
    async def test_execute_connection_refused(self, netconf_tool, mock_sandbox):
        """Test handling of connection refused error."""
        mock_sandbox.execute.side_effect = ConnectionRefusedError("Connection refused")
        
        result = await netconf_tool.execute(
            device="R1",
            operation="get-config",
            xpath="/interfaces"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert "connection refused" in result.error.lower()
        assert result.data[0]["status"] == "CONNECTION_ERROR"
        assert "port 830" in result.data[0]["message"]
        assert "CLI" in result.data[0]["hint"]  # Suggest fallback
    
    @pytest.mark.asyncio
    async def test_execute_timeout(self, netconf_tool, mock_sandbox):
        """Test handling of timeout error."""
        mock_sandbox.execute.side_effect = TimeoutError("Connection timeout")
        
        result = await netconf_tool.execute(
            device="R1",
            operation="get-config",
            xpath="/interfaces"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert "timeout" in result.error.lower()
        assert result.data[0]["status"] == "TIMEOUT_ERROR"
    
    @pytest.mark.asyncio
    async def test_execute_generic_exception(self, netconf_tool, mock_sandbox):
        """Test handling of generic exception."""
        mock_sandbox.execute.side_effect = Exception("Unknown error")
        
        result = await netconf_tool.execute(
            device="R1",
            operation="get-config",
            xpath="/interfaces"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert "failed" in result.error.lower()
        assert result.data == []
    
    @pytest.mark.asyncio
    async def test_execute_failure_result(self, netconf_tool, mock_sandbox):
        """Test handling of failed execution result."""
        mock_sandbox.execute.return_value = MockExecutionResult(
            success=False,
            output=None,
            error="RPC error: Invalid XPath"
        )
        
        result = await netconf_tool.execute(
            device="R1",
            operation="get-config",
            xpath="/invalid/path"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.metadata["success"] is False
        # NetconfAdapter should handle error


class TestCLITool:
    """Test CLITool BaseTool implementation."""
    
    @pytest.fixture
    def mock_sandbox(self):
        """Create mock NornirSandbox."""
        sandbox = MagicMock()
        sandbox.execute_cli_command = AsyncMock()
        sandbox.execute_cli_config = AsyncMock()
        return sandbox
    
    @pytest.fixture
    def cli_tool(self, mock_sandbox):
        """Create CLITool with mock sandbox."""
        return CLITool(sandbox=mock_sandbox)
    
    def test_initialization(self, cli_tool):
        """Test tool initialization."""
        assert cli_tool.name == "cli_execute"
        assert "CLI" in cli_tool.description
        assert "SSH" in cli_tool.description
    
    @pytest.mark.asyncio
    async def test_execute_missing_both_params(self, cli_tool):
        """Test execution without command or config_commands."""
        result = await cli_tool.execute(device="R1")
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert ("must provide" in result.error.lower() or "missing required" in result.error.lower())
        assert result.data[0]["status"] == "PARAM_ERROR"
    
    @pytest.mark.asyncio
    async def test_execute_both_params_conflict(self, cli_tool):
        """Test execution with both command and config_commands."""
        result = await cli_tool.execute(
            device="R1",
            command="show version",
            config_commands=["interface Gi0/0"]
        )
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert ("cannot provide both" in result.error.lower() or "conflicting parameters" in result.error.lower())
        assert result.data[0]["status"] == "PARAM_ERROR"
    
    @pytest.mark.asyncio
    async def test_execute_show_command_success(self, cli_tool, mock_sandbox):
        """Test successful show command with TextFSM parsing."""
        # Mock parsed output
        parsed_output = [
            {"interface": "GigabitEthernet0/0", "ip_address": "192.168.1.1", "status": "up"},
            {"interface": "GigabitEthernet0/1", "ip_address": "10.0.0.1", "status": "up"},
        ]
        
        mock_sandbox.execute_cli_command.return_value = MockExecutionResult(
            success=True,
            output=parsed_output,
            error=None,
            metadata={"parsed": True, "template": "cisco_ios_show_ip_interface_brief"}
        )
        
        result = await cli_tool.execute(
            device="R1",
            command="show ip interface brief"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.source == "cli"
        assert result.device == "R1"
        assert result.metadata["command"] == "show ip interface brief"
        assert result.metadata["is_config"] is False
        assert result.metadata["success"] is True
        assert "elapsed_ms" in result.metadata
        
        # Verify CLI execution call
        mock_sandbox.execute_cli_command.assert_called_once()
        call_kwargs = mock_sandbox.execute_cli_command.call_args.kwargs
        assert call_kwargs["device"] == "R1"
        assert call_kwargs["command"] == "show ip interface brief"
        assert call_kwargs["use_textfsm"] is True
    
    @pytest.mark.asyncio
    async def test_execute_config_commands_success(self, cli_tool, mock_sandbox):
        """Test successful configuration commands (triggers HITL)."""
        mock_sandbox.execute_cli_config.return_value = MockExecutionResult(
            success=True,
            output="Configuration applied successfully",
            error=None
        )
        
        config_cmds = [
            "interface GigabitEthernet0/0",
            "mtu 9000",
            "description Updated via OLAV"
        ]
        
        result = await cli_tool.execute(
            device="R1",
            config_commands=config_cmds
        )
        
        assert isinstance(result, ToolOutput)
        assert result.source == "cli"
        assert result.metadata["is_config"] is True
        assert result.metadata["requires_approval"] is True  # HITL flag
        assert result.metadata["config_commands"] == config_cmds
        
        # Verify config execution call
        mock_sandbox.execute_cli_config.assert_called_once()
        call_kwargs = mock_sandbox.execute_cli_config.call_args.kwargs
        assert call_kwargs["device"] == "R1"
        assert call_kwargs["commands"] == config_cmds
        assert call_kwargs["requires_approval"] is True
    
    @pytest.mark.asyncio
    async def test_execute_show_command_unparsed(self, cli_tool, mock_sandbox):
        """Test show command with unparsed (raw text) output."""
        raw_output = "Interface              IP-Address      OK? Method Status                Protocol\nGi0/0                  192.168.1.1     YES manual up                    up"
        
        mock_sandbox.execute_cli_command.return_value = MockExecutionResult(
            success=True,
            output=raw_output,
            error=None,
            metadata={"parsed": False}
        )
        
        result = await cli_tool.execute(
            device="R1",
            command="show ip interface brief"
        )
        
        assert isinstance(result, ToolOutput)
        # CLIAdapter should wrap raw text in dict
        assert result.metadata["success"] is True
    
    @pytest.mark.asyncio
    async def test_execute_connection_refused(self, cli_tool, mock_sandbox):
        """Test handling of SSH connection refused."""
        mock_sandbox.execute_cli_command.side_effect = ConnectionRefusedError("Connection refused")
        
        result = await cli_tool.execute(
            device="R1",
            command="show version"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert "connection refused" in result.error.lower()
        assert result.data[0]["status"] == "CONNECTION_ERROR"
        assert "port 22" in result.data[0]["message"]
    
    @pytest.mark.asyncio
    async def test_execute_generic_exception(self, cli_tool, mock_sandbox):
        """Test handling of generic exception."""
        mock_sandbox.execute_cli_command.side_effect = Exception("SSH timeout")
        
        result = await cli_tool.execute(
            device="R1",
            command="show version"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert "failed" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_execute_command_failure(self, cli_tool, mock_sandbox):
        """Test handling of failed command execution."""
        mock_sandbox.execute_cli_command.return_value = MockExecutionResult(
            success=False,
            output=None,
            error="% Invalid input detected"
        )
        
        result = await cli_tool.execute(
            device="R1",
            command="show invalid command"
        )
        
        assert isinstance(result, ToolOutput)
        assert result.metadata["success"] is False
        # CLIAdapter should handle error in ToolOutput.error


class TestNornirToolRegistration:
    """Test tool registration with ToolRegistry."""
    
    def test_tools_registered(self):
        """Test both tools are registered on import."""
        from olav.tools.base import ToolRegistry
        
        registered_names = [tool.name for tool in ToolRegistry.list_tools()]
        
        assert "netconf_execute" in registered_names
        assert "cli_execute" in registered_names
    
    def test_get_tool_by_name(self):
        """Test retrieving tools by name."""
        from olav.tools.base import ToolRegistry
        
        netconf_tool = ToolRegistry.get_tool("netconf_execute")
        assert netconf_tool is not None
        assert isinstance(netconf_tool, NetconfTool)
        
        cli_tool = ToolRegistry.get_tool("cli_execute")
        assert cli_tool is not None
        assert isinstance(cli_tool, CLITool)


class TestNornirToolEdgeCases:
    """Test edge cases and boundary conditions."""
    
    @pytest.mark.asyncio
    async def test_netconf_xpath_with_special_chars(self):
        """Test XPath with special characters."""
        mock_sandbox = MagicMock()
        mock_sandbox.execute = AsyncMock(return_value=MockExecutionResult(
            success=True,
            output="<data/>",
            error=None
        ))
        
        tool = NetconfTool(sandbox=mock_sandbox)
        
        xpath = "/interfaces/interface[name='Gi0/0']/config"
        result = await tool.execute(
            device="R1",
            operation="get-config",
            xpath=xpath
        )
        
        assert isinstance(result, ToolOutput)
        # Verify XPath is correctly included in RPC
        call_kwargs = mock_sandbox.execute.call_args.kwargs
        assert xpath in call_kwargs["command"]
    
    @pytest.mark.asyncio
    async def test_cli_config_empty_commands_list(self):
        """Test config commands with empty list."""
        mock_sandbox = MagicMock()
        mock_sandbox.execute_cli_config = AsyncMock(return_value=MockExecutionResult(
            success=True,
            output="",
            error=None
        ))
        
        tool = CLITool(sandbox=mock_sandbox)
        
        result = await tool.execute(
            device="R1",
            config_commands=[]
        )
        
        assert isinstance(result, ToolOutput)
        # Empty list is still a config operation
        assert result.metadata["is_config"] is True
    
    @pytest.mark.asyncio
    async def test_timing_metadata_present(self):
        """Test execution timing is tracked in metadata."""
        mock_sandbox = MagicMock()
        mock_sandbox.execute_cli_command = AsyncMock(return_value=MockExecutionResult(
            success=True,
            output=[],
            metadata={"parsed": True}
        ))
        
        tool = CLITool(sandbox=mock_sandbox)
        
        result = await tool.execute(
            device="R1",
            command="show version"
        )
        
        assert "elapsed_ms" in result.metadata
        assert isinstance(result.metadata["elapsed_ms"], float)
        assert result.metadata["elapsed_ms"] >= 0

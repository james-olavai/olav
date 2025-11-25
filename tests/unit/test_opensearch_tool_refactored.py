"""Unit tests for OpenSearch RAG tools (refactored to BaseTool protocol)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from olav.tools.opensearch_tool_refactored import (
    OpenConfigSchemaTool,
    EpisodicMemoryTool,
)
from olav.tools.base import ToolRegistry


class TestOpenConfigSchemaTool:
    """Test suite for OpenConfigSchemaTool."""
    
    @pytest.fixture(autouse=True)
    def cleanup_registry(self):
        """Clear tool registry before and after each test."""
        from olav.tools.base import ToolRegistry
        # Clear before test
        if "openconfig_schema_search" in ToolRegistry._tools:
            del ToolRegistry._tools["openconfig_schema_search"]
        yield
        # Clear after test
        if "openconfig_schema_search" in ToolRegistry._tools:
            del ToolRegistry._tools["openconfig_schema_search"]
    
    @pytest.fixture
    def mock_memory(self):
        """Mock OpenSearchMemory."""
        memory = MagicMock()
        memory.search_schema = AsyncMock()
        return memory
    
    @pytest.fixture
    def schema_tool(self, mock_memory):
        """Create OpenConfigSchemaTool with mocked memory."""
        tool = OpenConfigSchemaTool(memory=mock_memory)
        ToolRegistry.register(tool)
        return tool
    
    def test_initialization(self, schema_tool):
        """Test tool initialization and properties."""
        assert schema_tool.name == "openconfig_schema_search"
        assert "OpenConfig YANG schema" in schema_tool.description
        assert "XPaths" in schema_tool.description
    
    def test_lazy_memory_loading(self):
        """Test lazy loading of OpenSearchMemory."""
        tool = OpenConfigSchemaTool(memory=None)
        # Memory should be created on first access
        assert tool.memory is not None
        assert tool._memory is not None
    
    @pytest.mark.asyncio
    async def test_execute_missing_intent(self, schema_tool):
        """Test execute with empty intent parameter."""
        result = await schema_tool.execute(intent="")
        
        assert result.error is not None
        assert "cannot be empty" in result.error.lower()
        assert result.data == []
    
    @pytest.mark.asyncio
    async def test_execute_success(self, schema_tool, mock_memory):
        """Test successful schema search."""
        # Mock search results
        mock_results = [
            {
                "xpath": "/network-instances/network-instance/protocols/protocol/bgp/global/config/as",
                "description": "Local autonomous system number",
                "type": "uint32",
                "example": {"as": 65000},
            }
        ]
        mock_memory.search_schema.return_value = mock_results
        
        result = await schema_tool.execute(
            intent="configure BGP AS number",
            device_type="network-instance",
        )
        
        # Verify search_schema was called with correct parameters
        mock_memory.search_schema.assert_awaited_once()
        call_args = mock_memory.search_schema.call_args
        assert call_args.kwargs["index"] == "openconfig-schema"
        assert call_args.kwargs["size"] == 5
        
        # Verify query structure
        query = call_args.kwargs["query"]
        assert query["bool"]["must"][0]["match"]["description"] == "configure BGP AS number"
        assert query["bool"]["must"][1]["term"]["module"] == "network-instance"
        
        # Verify result (adapter should normalize)
        assert result.error is None
        assert result.source == "opensearch"
        assert "intent" in result.metadata
        assert "elapsed_ms" in result.metadata
    
    @pytest.mark.asyncio
    async def test_execute_custom_max_results(self, schema_tool, mock_memory):
        """Test execute with custom max_results parameter."""
        mock_memory.search_schema.return_value = []
        
        await schema_tool.execute(
            intent="add VLAN",
            device_type="interfaces",
            max_results=10,
        )
        
        call_args = mock_memory.search_schema.call_args
        assert call_args.kwargs["size"] == 10
    
    @pytest.mark.asyncio
    async def test_execute_connection_error(self, schema_tool, mock_memory):
        """Test execute with OpenSearch connection error."""
        mock_memory.search_schema.side_effect = ConnectionError("Connection refused")
        
        result = await schema_tool.execute(intent="test query")
        
        assert result.error is not None
        assert "connection failed" in result.error.lower()
        assert result.data == []
    
    @pytest.mark.asyncio
    async def test_execute_timeout_error(self, schema_tool, mock_memory):
        """Test execute with OpenSearch timeout."""
        mock_memory.search_schema.side_effect = TimeoutError("Query timeout")
        
        result = await schema_tool.execute(intent="test query")
        
        assert result.error is not None
        assert "timeout" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_execute_generic_exception(self, schema_tool, mock_memory):
        """Test execute with generic exception."""
        mock_memory.search_schema.side_effect = Exception("Unexpected error")
        
        result = await schema_tool.execute(intent="test query")
        
        assert result.error is not None
        assert result.error is not None
        assert result.data == []


class TestEpisodicMemoryTool:
    """Test suite for EpisodicMemoryTool."""
    
    @pytest.fixture(autouse=True)
    def cleanup_registry(self):
        """Clear tool registry before and after each test."""
        from olav.tools.base import ToolRegistry
        # Clear before test
        if "episodic_memory_search" in ToolRegistry._tools:
            del ToolRegistry._tools["episodic_memory_search"]
        yield
        # Clear after test
        if "episodic_memory_search" in ToolRegistry._tools:
            del ToolRegistry._tools["episodic_memory_search"]
    
    @pytest.fixture
    def mock_memory(self):
        """Mock OpenSearchMemory."""
        memory = MagicMock()
        memory.search_schema = AsyncMock()
        return memory
    
    @pytest.fixture
    def memory_tool(self, mock_memory):
        """Create EpisodicMemoryTool with mocked memory."""
        tool = EpisodicMemoryTool(memory=mock_memory)
        ToolRegistry.register(tool)
        return tool
    
    def test_initialization(self, memory_tool):
        """Test tool initialization and properties."""
        assert memory_tool.name == "episodic_memory_search"
        assert "episodic memory" in memory_tool.description
        assert "historical success patterns" in memory_tool.description
    
    def test_lazy_memory_loading(self):
        """Test lazy loading of OpenSearchMemory."""
        tool = EpisodicMemoryTool(memory=None)
        assert tool.memory is not None
    
    @pytest.mark.asyncio
    async def test_execute_missing_intent(self, memory_tool):
        """Test execute with empty intent parameter."""
        result = await memory_tool.execute(intent="")
        
        assert result.error is not None
        assert "cannot be empty" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_execute_success_only_successful(self, memory_tool, mock_memory):
        """Test successful episodic memory search (only successful entries)."""
        mock_results = [
            {
                "intent": "add BGP neighbor 192.168.1.1 AS 65001",
                "xpath": "/network-instances/.../neighbors/neighbor[neighbor-address=192.168.1.1]/config",
                "success": True,
                "context": {"device": "router1", "timestamp": "2024-01-15T10:30:00Z"},
            }
        ]
        mock_memory.search_schema.return_value = mock_results
        
        result = await memory_tool.execute(
            intent="configure BGP neighbor",
            only_successful=True,
        )
        
        # Verify search_schema was called
        mock_memory.search_schema.assert_awaited_once()
        call_args = mock_memory.search_schema.call_args
        assert call_args.kwargs["index"] == "olav-episodic-memory"
        assert call_args.kwargs["size"] == 3
        
        # Verify query filters by success=True
        query = call_args.kwargs["query"]
        must_clauses = query["bool"]["must"]
        assert len(must_clauses) == 2
        assert must_clauses[0]["match"]["intent"] == "configure BGP neighbor"
        assert must_clauses[1]["term"]["success"] is True
        
        # Verify result
        assert result.error is None
        assert result.source == "opensearch"
        assert "intent" in result.metadata
    
    @pytest.mark.asyncio
    async def test_execute_success_all_entries(self, memory_tool, mock_memory):
        """Test episodic memory search (include failed entries)."""
        mock_memory.search_schema.return_value = []
        
        await memory_tool.execute(
            intent="test query",
            only_successful=False,
        )
        
        # Verify query does NOT filter by success
        call_args = mock_memory.search_schema.call_args
        query = call_args.kwargs["query"]
        must_clauses = query["bool"]["must"]
        assert len(must_clauses) == 1  # Only intent match, no success filter
        assert must_clauses[0]["match"]["intent"] == "test query"
    
    @pytest.mark.asyncio
    async def test_execute_custom_max_results(self, memory_tool, mock_memory):
        """Test execute with custom max_results parameter."""
        mock_memory.search_schema.return_value = []
        
        await memory_tool.execute(
            intent="test",
            max_results=10,
        )
        
        call_args = mock_memory.search_schema.call_args
        assert call_args.kwargs["size"] == 10
    
    @pytest.mark.asyncio
    async def test_execute_connection_error(self, memory_tool, mock_memory):
        """Test execute with OpenSearch connection error."""
        mock_memory.search_schema.side_effect = ConnectionError("Connection refused")
        
        result = await memory_tool.execute(intent="test query")
        
        assert result.error is not None
        assert "connection failed" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_execute_timeout_error(self, memory_tool, mock_memory):
        """Test execute with OpenSearch timeout."""
        mock_memory.search_schema.side_effect = TimeoutError("Query timeout")
        
        result = await memory_tool.execute(intent="test query")
        
        assert result.error is not None
        assert "timeout" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_execute_generic_exception(self, memory_tool, mock_memory):
        """Test execute with generic exception."""
        mock_memory.search_schema.side_effect = Exception("Unexpected error")
        
        result = await memory_tool.execute(intent="test query")
        
        assert result.error is not None
        assert result.error is not None


class TestOpenSearchToolsRegistration:
    """Test ToolRegistry registration for OpenSearch tools."""
    
    @pytest.fixture(autouse=True)
    def setup_tools(self):
        """Register tools before tests and cleanup after."""
        from olav.tools.base import ToolRegistry
        # Clear first
        if "openconfig_schema_search" in ToolRegistry._tools:
            del ToolRegistry._tools["openconfig_schema_search"]
        if "episodic_memory_search" in ToolRegistry._tools:
            del ToolRegistry._tools["episodic_memory_search"]
        
        # Register tools
        schema_tool = OpenConfigSchemaTool()
        memory_tool = EpisodicMemoryTool()
        ToolRegistry.register(schema_tool)
        ToolRegistry.register(memory_tool)
        
        yield
        
        # Cleanup
        if "openconfig_schema_search" in ToolRegistry._tools:
            del ToolRegistry._tools["openconfig_schema_search"]
        if "episodic_memory_search" in ToolRegistry._tools:
            del ToolRegistry._tools["episodic_memory_search"]
    
    def test_tools_registered(self):
        """Test that both OpenSearch tools are registered."""
        registered = ToolRegistry.list_tools()
        tool_names = [tool.name for tool in registered]
        assert "openconfig_schema_search" in tool_names
        assert "episodic_memory_search" in tool_names
    
    def test_get_tool_by_name(self):
        """Test retrieving tools by name from registry."""
        schema_tool = ToolRegistry.get_tool("openconfig_schema_search")
        assert schema_tool is not None
        assert isinstance(schema_tool, OpenConfigSchemaTool)
        
        memory_tool = ToolRegistry.get_tool("episodic_memory_search")
        assert memory_tool is not None
        assert isinstance(memory_tool, EpisodicMemoryTool)


class TestOpenSearchToolsEdgeCases:
    """Test edge cases for OpenSearch tools."""
    
    @pytest.fixture(autouse=True)
    def cleanup_registry(self):
        """Clear tool registry before and after each test."""
        from olav.tools.base import ToolRegistry
        if "openconfig_schema_search" in ToolRegistry._tools:
            del ToolRegistry._tools["openconfig_schema_search"]
        if "episodic_memory_search" in ToolRegistry._tools:
            del ToolRegistry._tools["episodic_memory_search"]
        yield
        if "openconfig_schema_search" in ToolRegistry._tools:
            del ToolRegistry._tools["openconfig_schema_search"]
        if "episodic_memory_search" in ToolRegistry._tools:
            del ToolRegistry._tools["episodic_memory_search"]
    
    @pytest.fixture
    def mock_memory(self):
        """Mock OpenSearchMemory."""
        memory = MagicMock()
        memory.search_schema = AsyncMock()
        return memory
    
    @pytest.mark.asyncio
    async def test_whitespace_only_intent(self, mock_memory):
        """Test intent with only whitespace characters."""
        tool = OpenConfigSchemaTool(memory=mock_memory)
        result = await tool.execute(intent="   \t\n  ")
        
        assert result.error is not None
        assert "cannot be empty" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_timing_metadata_present(self, mock_memory):
        """Test that elapsed_ms is always included in metadata."""
        mock_memory.search_schema.return_value = []
        
        tool = OpenConfigSchemaTool(memory=mock_memory)
        result = await tool.execute(intent="test")
        
        assert "elapsed_ms" in result.metadata
        assert isinstance(result.metadata["elapsed_ms"], int)
        assert result.metadata["elapsed_ms"] >= 0
    
    @pytest.mark.asyncio
    async def test_result_count_metadata(self, mock_memory):
        """Test that result_count is tracked in metadata."""
        mock_memory.search_schema.return_value = [{"xpath": "/test1"}, {"xpath": "/test2"}]
        
        tool = EpisodicMemoryTool(memory=mock_memory)
        result = await tool.execute(intent="test")
        
        assert result.metadata["result_count"] == 2

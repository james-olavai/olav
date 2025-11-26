"""Tests for MemoryWriter component."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from olav.core.memory_writer import MemoryWriter, get_memory_writer
from olav.tools.base import ToolOutput


class TestMemoryWriter:
    """Test MemoryWriter captures successful executions."""
    
    @pytest.fixture
    def mock_memory(self):
        """Mock OpenSearchMemory."""
        memory = MagicMock()
        memory.store_episodic_memory = AsyncMock()
        return memory
    
    @pytest.fixture
    def memory_writer(self, mock_memory):
        """Create MemoryWriter with mocked memory."""
        return MemoryWriter(memory=mock_memory)
    
    @pytest.fixture
    def sample_tool_output(self):
        """Sample successful tool output."""
        return ToolOutput(
            source="suzieq_query",
            device="R1",
            data=[
                {"hostname": "R1", "peer": "192.168.1.2", "state": "Established"},
                {"hostname": "R1", "peer": "192.168.1.3", "state": "Established"},
            ],
            metadata={"elapsed_ms": 234, "table": "bgp"},
            error=None,
        )
    
    @pytest.mark.asyncio
    async def test_capture_success_suzieq(self, memory_writer, mock_memory, sample_tool_output):
        """Test capturing successful SuzieQ query."""
        await memory_writer.capture_success(
            intent="查询 R1 BGP 状态",
            tool_used="suzieq_query",
            parameters={"table": "bgp", "hostname": "R1", "method": "get"},
            tool_output=sample_tool_output,
            strategy_used="fast_path",
            execution_time_ms=234,
        )
        
        # Verify store_episodic_memory was called
        mock_memory.store_episodic_memory.assert_called_once()
        call_args = mock_memory.store_episodic_memory.call_args[1]
        
        # Check arguments
        assert call_args["intent"] == "查询 R1 BGP 状态"
        assert call_args["xpath"] == "table=bgp, hostname=R1, method=get"
        assert call_args["success"] is True
        assert call_args["context"]["tool_used"] == "suzieq_query"
        assert call_args["context"]["device_type"] == "R1"
        assert call_args["context"]["strategy_used"] == "fast_path"
        assert call_args["context"]["execution_time_ms"] == 234
        assert "2 records retrieved" in call_args["context"]["result_summary"]
    
    @pytest.mark.asyncio
    async def test_capture_success_netconf(self, memory_writer, mock_memory):
        """Test capturing successful NETCONF execution."""
        tool_output = ToolOutput(
            source="netconf_execute",
            device="juniper-r1",
            data=[{"config": "ok"}],
            metadata={"elapsed_ms": 1823},
            error=None,
        )
        
        await memory_writer.capture_success(
            intent="配置 BGP neighbor 192.168.1.1",
            tool_used="netconf_execute",
            parameters={
                "operation": "edit-config",
                "xpath": "/network-instances/network-instance/protocols/protocol/bgp/neighbors",
                "config": {"neighbor-address": "192.168.1.1"},
            },
            tool_output=tool_output,
            strategy_used="fast_path",
            execution_time_ms=1823,
        )
        
        mock_memory.store_episodic_memory.assert_called_once()
        call_args = mock_memory.store_episodic_memory.call_args[1]
        
        assert call_args["intent"] == "配置 BGP neighbor 192.168.1.1"
        assert "network-instances" in call_args["xpath"]
        assert call_args["context"]["tool_used"] == "netconf_execute"
        assert call_args["context"]["device_type"] == "juniper-r1"
    
    @pytest.mark.asyncio
    async def test_skip_failed_execution(self, memory_writer, mock_memory):
        """Test that failed executions are not captured as successes."""
        failed_output = ToolOutput(
            source="suzieq_query",
            device="R1",
            data=[],
            metadata={},
            error="Connection timeout",
        )
        
        await memory_writer.capture_success(
            intent="查询 R1 状态",
            tool_used="suzieq_query",
            parameters={"table": "bgp"},
            tool_output=failed_output,
            strategy_used="fast_path",
        )
        
        # Should not call store_episodic_memory for failed executions
        mock_memory.store_episodic_memory.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_capture_failure(self, memory_writer, mock_memory):
        """Test capturing failed execution for debugging."""
        await memory_writer.capture_failure(
            intent="查询不存在的设备",
            tool_used="suzieq_query",
            parameters={"table": "bgp", "hostname": "NONEXISTENT"},
            error="Device not found",
            strategy_used="fast_path",
        )
        
        mock_memory.store_episodic_memory.assert_called_once()
        call_args = mock_memory.store_episodic_memory.call_args[1]
        
        assert call_args["success"] is False
        assert call_args["context"]["error"] == "Device not found"
    
    def test_build_xpath_representation_suzieq(self, memory_writer):
        """Test XPath representation for SuzieQ queries."""
        xpath = memory_writer._build_xpath_representation(
            "suzieq_query",
            {"table": "bgp", "hostname": "R1", "method": "get", "namespace": "default"}
        )
        
        assert "table=bgp" in xpath
        assert "hostname=R1" in xpath
        assert "method=get" in xpath
        assert "namespace=default" in xpath
    
    def test_build_xpath_representation_netconf(self, memory_writer):
        """Test XPath representation for NETCONF."""
        xpath = memory_writer._build_xpath_representation(
            "netconf_execute",
            {"xpath": "/interfaces/interface/config", "operation": "get-config"}
        )
        
        assert xpath == "/interfaces/interface/config"
    
    def test_build_xpath_representation_cli(self, memory_writer):
        """Test XPath representation for CLI."""
        xpath = memory_writer._build_xpath_representation(
            "cli_execute",
            {"command": "show bgp summary"}
        )
        
        assert xpath == "command: show bgp summary"
    
    def test_generate_result_summary_single_record(self, memory_writer):
        """Test result summary for single record."""
        output = ToolOutput(
            source="test",
            device="R1",
            data=[{"hostname": "R1", "status": "up", "ip": "10.0.0.1"}],
            metadata={},
            error=None,
        )
        
        summary = memory_writer._generate_result_summary(output)
        assert "1 record" in summary
        assert "R1" in summary or "up" in summary or "10.0.0.1" in summary
    
    def test_generate_result_summary_multiple_records(self, memory_writer):
        """Test result summary for multiple records."""
        output = ToolOutput(
            source="test",
            device="unknown",
            data=[{"id": i} for i in range(15)],
            metadata={},
            error=None,
        )
        
        summary = memory_writer._generate_result_summary(output)
        assert "15 records" in summary
    
    def test_generate_result_summary_empty(self, memory_writer):
        """Test result summary for empty data."""
        output = ToolOutput(
            source="test",
            device="unknown",
            data=[],
            metadata={},
            error=None,
        )
        
        summary = memory_writer._generate_result_summary(output)
        assert summary == "No data returned"
    
    def test_get_memory_writer_singleton(self):
        """Test singleton pattern for get_memory_writer."""
        writer1 = get_memory_writer()
        writer2 = get_memory_writer()
        
        assert writer1 is writer2
    
    @pytest.mark.asyncio
    async def test_error_handling_doesnt_break_workflow(self, memory_writer, mock_memory):
        """Test that memory write failures don't break main workflow."""
        # Make store_episodic_memory raise exception
        mock_memory.store_episodic_memory.side_effect = Exception("OpenSearch connection failed")
        
        tool_output = ToolOutput(
            source="suzieq_query",
            device="R1",
            data=[{"test": "data"}],
            metadata={"elapsed_ms": 100},
            error=None,
        )
        
        # Should not raise, only log error
        await memory_writer.capture_success(
            intent="test query",
            tool_used="suzieq_query",
            parameters={"table": "test"},
            tool_output=tool_output,
            strategy_used="fast_path",
        )
        
        # Verify it tried to call (and failed gracefully)
        mock_memory.store_episodic_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_agentic_rag_disabled_skips_capture(self, mock_memory, sample_tool_output):
        """Test that capture is skipped when agentic RAG is disabled."""
        from olav.core import settings
        
        # Temporarily disable agentic RAG
        original_value = settings.settings.enable_agentic_rag
        settings.settings.enable_agentic_rag = False
        
        try:
            writer = MemoryWriter(memory=mock_memory)
            await writer.capture_success(
                intent="test query",
                tool_used="suzieq_query",
                parameters={"table": "bgp"},
                tool_output=sample_tool_output,
                strategy_used="fast_path",
            )
            
            # Should NOT call store_episodic_memory when disabled
            mock_memory.store_episodic_memory.assert_not_called()
        finally:
            # Restore original value
            settings.settings.enable_agentic_rag = original_value


class TestMemoryWriterIntegration:
    """Integration tests with actual OpenSearch (requires running OpenSearch)."""
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_opensearch_write(self):
        """Test actual write to OpenSearch episodic-memory index.
        
        Requires:
            - OpenSearch running at localhost:9200
            - olav-episodic-memory index initialized
        """
        from olav.core.memory import OpenSearchMemory
        
        memory = OpenSearchMemory()
        writer = MemoryWriter(memory=memory)
        
        tool_output = ToolOutput(
            source="suzieq_query",
            device="test-router",
            data=[{"hostname": "test-router", "state": "up"}],
            metadata={"elapsed_ms": 50},
            error=None,
        )
        
        await writer.capture_success(
            intent="integration test query",
            tool_used="suzieq_query",
            parameters={"table": "test"},
            tool_output=tool_output,
            strategy_used="fast_path",
            execution_time_ms=50,
        )
        
        # Verify by searching
        results = await memory.search_schema(
            index="olav-episodic-memory",
            query={"match": {"intent": "integration test"}},
            size=1,
        )
        
        assert len(results) > 0
        assert results[0]["intent"] == "integration test query"
        assert results[0]["success"] is True

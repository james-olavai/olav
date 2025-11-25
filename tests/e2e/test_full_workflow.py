"""
End-to-end workflow integration tests.

Tests the complete OLAV architecture:
Query → StrategySelector → Strategy.execute() → ToolRegistry → Tool.execute() → Adapter → Validation

These tests use:
- Mock LLM for deterministic responses
- Real ToolRegistry for tool discovery
- Real tools (with mocked backends) for execution
- Real adapters for normalization
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import AIMessage
from datetime import datetime

from olav.strategies.selector import StrategySelector, create_strategy_selector
from olav.strategies.fast_path import FastPathStrategy
from olav.strategies.deep_path import DeepPathStrategy
from olav.tools.base import ToolRegistry, ToolOutput
from olav.tools.suzieq_tool import SuzieQTool, SuzieQSchemaSearchTool
from olav.tools.netbox_tool_refactored import NetBoxAPITool, NetBoxSchemaSearchTool
from olav.tools.nornir_tool_refactored import NetconfTool, CLITool


class TestE2EFastPathWorkflow:
    """Test end-to-end Fast Path workflow."""
    
    @pytest.fixture(autouse=True)
    def setup_registry(self):
        """Clear and setup ToolRegistry for each test."""
        ToolRegistry._tools.clear()
        
        # Register tools
        suzieq_tool = SuzieQTool()
        suzieq_schema_tool = SuzieQSchemaSearchTool()
        netbox_tool = NetBoxAPITool()
        netbox_schema_tool = NetBoxSchemaSearchTool()
        netconf_tool = NetconfTool()
        cli_tool = CLITool()
        
        ToolRegistry.register(suzieq_tool)
        ToolRegistry.register(suzieq_schema_tool)
        ToolRegistry.register(netbox_tool)
        ToolRegistry.register(netbox_schema_tool)
        ToolRegistry.register(netconf_tool)
        ToolRegistry.register(cli_tool)
        
        yield
        
        # Cleanup
        ToolRegistry._tools.clear()
    
    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM with controlled responses."""
        llm = MagicMock()
        llm.ainvoke = AsyncMock()
        return llm
    
    @pytest.mark.asyncio
    async def test_fast_path_suzieq_query_workflow(self, mock_llm):
        """
        Test Fast Path workflow with SuzieQ tool.
        
        Flow:
        1. User query: "查询 R1 的 BGP 状态"
        2. Strategy extracts: suzieq_query(table="bgp", hostname="R1")
        3. ToolRegistry finds SuzieQTool
        4. Tool executes (mocked SuzieQ backend)
        5. Adapter normalizes to ToolOutput
        6. Strategy formats answer
        """
        # Step 1: Setup LLM responses
        def mock_llm_responses(messages):
            prompt_text = str(messages)
            
            # Parameter extraction response
            if "参数提取" in prompt_text or "Extract" in prompt_text:
                return AIMessage(content="""{
                    "tool": "suzieq_query",
                    "parameters": {
                        "table": "bgp",
                        "hostname": "R1"
                    },
                    "confidence": 0.95,
                    "reasoning": "Simple BGP status query for single device R1"
                }""")
            
            # Answer formatting response
            elif "格式化答案" in prompt_text or "Format" in prompt_text:
                return AIMessage(content="""{
                    "answer": "R1 has 2 BGP neighbors in Established state",
                    "data_used": ["hostname", "peerHostname", "state"],
                    "confidence": 0.92
                }""")
            
            return AIMessage(content="{}")
        
        mock_llm.ainvoke = AsyncMock(side_effect=mock_llm_responses)
        
        # Step 2: Mock SuzieQ backend
        with patch('olav.tools.suzieq_tool.SuzieQContext') as mock_ctx:
            # Mock SuzieQ query result
            mock_sq_obj = MagicMock()
            mock_sq_obj.get.return_value = MagicMock(
                to_dict=lambda orient: {
                    "records": [
                        {
                            "hostname": "R1",
                            "peerHostname": "R2",
                            "state": "Established",
                            "asn": 65001
                        },
                        {
                            "hostname": "R1",
                            "peerHostname": "R3",
                            "state": "Established",
                            "asn": 65002
                        }
                    ]
                }
            )
            
            mock_ctx_instance = MagicMock()
            mock_ctx.return_value = mock_ctx_instance
            
            # Setup get_sqobject to return mock object
            with patch('olav.tools.suzieq_tool.get_sqobject', return_value=lambda context: mock_sq_obj):
                # Step 3: Create strategy with real ToolRegistry
                strategy = FastPathStrategy(
                    llm=mock_llm,
                    tool_registry=ToolRegistry,
                    confidence_threshold=0.7
                )
                
                # Step 4: Execute workflow
                result = await strategy.execute("查询 R1 的 BGP 状态")
                
                # Step 5: Verify complete workflow
                assert result["success"] is True
                assert "answer" in result
                assert "BGP" in result["answer"] or "neighbor" in result["answer"].lower()
                
                # Verify tool was called via ToolRegistry
                assert "tool_output" in result
                tool_output = result["tool_output"]
                assert isinstance(tool_output, ToolOutput)
                assert tool_output.source == "suzieq"
                assert tool_output.device == "R1"
                assert tool_output.error is None
                assert len(tool_output.data) > 0
                
                # Verify metadata
                assert result["metadata"]["strategy"] == "fast_path"
                assert result["metadata"]["tool"] == "suzieq_query"
                assert result["metadata"]["confidence"] >= 0.7
    
    @pytest.mark.asyncio
    async def test_fast_path_tool_not_found_error(self, mock_llm):
        """Test Fast Path handles tool not found gracefully."""
        
        def mock_extraction(messages):
            return AIMessage(content="""{
                "tool": "nonexistent_tool",
                "parameters": {},
                "confidence": 0.8,
                "reasoning": "Testing error handling"
            }""")
        
        mock_llm.ainvoke = AsyncMock(side_effect=mock_extraction)
        
        strategy = FastPathStrategy(
            llm=mock_llm,
            tool_registry=ToolRegistry,
            confidence_threshold=0.7
        )
        
        result = await strategy.execute("test query")
        
        # Should fail with clear error
        assert result["success"] is False
        assert "tool_error" in result.get("reason", "")
        assert "tool_output" in result
        assert result["tool_output"].error is not None
        assert "not registered" in result["tool_output"].error.lower()


class TestE2EStrategySelection:
    """Test end-to-end strategy selection."""
    
    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM."""
        llm = MagicMock()
        llm.ainvoke = AsyncMock()
        return llm
    
    @pytest.mark.asyncio
    async def test_selector_routes_to_fast_path(self, mock_llm):
        """Test selector identifies Fast Path queries."""
        selector = create_strategy_selector(llm=mock_llm)
        
        # Simple status query -> Fast Path
        decision = await selector.select("查询 R1 的接口状态")
        
        assert decision.strategy == "fast_path"
        assert decision.confidence >= 0.8
        assert "simple" in decision.reasoning.lower() or "single" in decision.reasoning.lower()
    
    @pytest.mark.asyncio
    async def test_selector_routes_to_deep_path(self, mock_llm):
        """Test selector identifies Deep Path queries."""
        selector = create_strategy_selector(llm=mock_llm)
        
        # Diagnostic query -> Deep Path
        decision = await selector.select("为什么 R1 的 BGP 无法建立？")
        
        assert decision.strategy == "deep_path"
        assert decision.confidence >= 0.8
        assert "why" in decision.reasoning.lower() or "diagnostic" in decision.reasoning.lower()
    
    @pytest.mark.asyncio
    async def test_selector_routes_to_batch_path(self, mock_llm):
        """Test selector identifies Batch Path queries."""
        selector = create_strategy_selector(llm=mock_llm)
        
        # Multi-device query -> Batch Path
        decision = await selector.select("批量检查所有路由器的 BGP 状态")
        
        assert decision.strategy == "batch_path"
        assert decision.confidence >= 0.8
        assert "batch" in decision.reasoning.lower() or "multi" in decision.reasoning.lower()
    
    @pytest.mark.asyncio
    async def test_selector_to_strategy_instantiation(self, mock_llm):
        """Test getting strategy class from selector decision."""
        selector = create_strategy_selector(llm=mock_llm)
        
        decision = await selector.select("查询 R1 状态")
        
        # Get strategy class
        strategy_class = StrategySelector.get_strategy_class(decision.strategy)
        
        # Should be FastPathStrategy
        assert strategy_class == FastPathStrategy
        
        # Verify can instantiate with ToolRegistry
        strategy = strategy_class(llm=mock_llm, tool_registry=ToolRegistry)
        assert strategy is not None
        assert hasattr(strategy, "execute")


class TestE2EToolRegistryIntegration:
    """Test ToolRegistry integration across workflow."""
    
    @pytest.fixture(autouse=True)
    def setup_registry(self):
        """Clear registry before each test."""
        ToolRegistry._tools.clear()
        yield
        ToolRegistry._tools.clear()
    
    def test_tool_registration_and_discovery(self):
        """Test tools can be registered and discovered."""
        # Register a tool
        suzieq_tool = SuzieQTool()
        ToolRegistry.register(suzieq_tool)
        
        # Verify discovery
        tools = ToolRegistry.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "suzieq_query"
        
        # Verify get_tool
        retrieved = ToolRegistry.get_tool("suzieq_query")
        assert retrieved is not None
        assert retrieved.name == "suzieq_query"
    
    def test_multiple_tool_registration(self):
        """Test multiple tools can coexist."""
        # Register all tools
        tools_to_register = [
            SuzieQTool(),
            SuzieQSchemaSearchTool(),
            NetBoxAPITool(),
            NetBoxSchemaSearchTool(),
            NetconfTool(),
            CLITool()
        ]
        
        for tool in tools_to_register:
            ToolRegistry.register(tool)
        
        # Verify all registered
        all_tools = ToolRegistry.list_tools()
        assert len(all_tools) == 6
        
        tool_names = [t.name for t in all_tools]
        assert "suzieq_query" in tool_names
        assert "suzieq_schema_search" in tool_names
        assert "netbox_api" in tool_names
        assert "netbox_schema_search" in tool_names
        assert "netconf_execute" in tool_names
        assert "cli_execute" in tool_names
    
    @pytest.mark.asyncio
    async def test_tool_execution_via_registry(self):
        """Test tools execute correctly when retrieved from registry."""
        # Register SuzieQ tool
        suzieq_tool = SuzieQTool()
        ToolRegistry.register(suzieq_tool)
        
        # Get tool from registry
        tool = ToolRegistry.get_tool("suzieq_query")
        assert tool is not None
        
        # Mock backend and execute
        with patch('olav.tools.suzieq_tool.SuzieQContext') as mock_ctx:
            mock_sq_obj = MagicMock()
            mock_sq_obj.get.return_value = MagicMock(
                to_dict=lambda orient: {"records": [{"hostname": "R1"}]}
            )
            mock_ctx.return_value = MagicMock()
            
            with patch('olav.tools.suzieq_tool.get_sqobject', return_value=lambda context: mock_sq_obj):
                result = await tool.execute(table="bgp", hostname="R1")
                
                assert isinstance(result, ToolOutput)
                assert result.source == "suzieq"
                assert result.error is None


class TestE2EAdapterIntegration:
    """Test adapter normalization in workflow."""
    
    @pytest.fixture(autouse=True)
    def setup_registry(self):
        """Setup registry."""
        ToolRegistry._tools.clear()
        suzieq_tool = SuzieQTool()
        ToolRegistry.register(suzieq_tool)
        yield
        ToolRegistry._tools.clear()
    
    @pytest.mark.asyncio
    async def test_suzieq_adapter_normalization(self):
        """Test SuzieQ adapter normalizes data correctly."""
        tool = ToolRegistry.get_tool("suzieq_query")
        
        with patch('olav.tools.suzieq_tool.SuzieQContext') as mock_ctx:
            # Mock DataFrame result
            mock_sq_obj = MagicMock()
            mock_sq_obj.get.return_value = MagicMock(
                to_dict=lambda orient: {
                    "records": [
                        {"hostname": "R1", "state": "Established", "asn": 65001},
                        {"hostname": "R2", "state": "Idle", "asn": 65002}
                    ]
                }
            )
            mock_ctx.return_value = MagicMock()
            
            with patch('olav.tools.suzieq_tool.get_sqobject', return_value=lambda context: mock_sq_obj):
                result = await tool.execute(table="bgp", hostname="multi")
                
                # Verify adapter normalized to ToolOutput
                assert isinstance(result, ToolOutput)
                assert result.source == "suzieq"
                assert result.device == "multi"
                assert isinstance(result.data, list)
                assert len(result.data) == 2
                
                # Verify data structure
                assert all(isinstance(d, dict) for d in result.data)
                assert result.data[0]["hostname"] == "R1"
                assert result.data[1]["hostname"] == "R2"
                
                # Verify metadata
                assert "table" in result.metadata
                assert result.metadata["table"] == "bgp"


class TestE2EErrorHandling:
    """Test error handling across workflow."""
    
    @pytest.fixture(autouse=True)
    def setup_registry(self):
        """Setup registry."""
        ToolRegistry._tools.clear()
        suzieq_tool = SuzieQTool()
        ToolRegistry.register(suzieq_tool)
        yield
        ToolRegistry._tools.clear()
    
    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM."""
        llm = MagicMock()
        llm.ainvoke = AsyncMock()
        return llm
    
    @pytest.mark.asyncio
    async def test_missing_required_parameter_error(self, mock_llm):
        """Test tool handles missing required parameters."""
        tool = ToolRegistry.get_tool("suzieq_query")
        
        # Execute without required 'table' parameter
        result = await tool.execute(hostname="R1")
        
        # Should return error in ToolOutput
        assert isinstance(result, ToolOutput)
        assert result.error is not None
        assert "table" in result.error.lower()
        assert result.data == []
    
    @pytest.mark.asyncio
    async def test_backend_connection_error(self, mock_llm):
        """Test tool handles backend connection errors."""
        tool = ToolRegistry.get_tool("suzieq_query")
        
        # Mock connection error
        with patch('olav.tools.suzieq_tool.SuzieQContext') as mock_ctx:
            mock_ctx.side_effect = ConnectionError("Cannot connect to SuzieQ")
            
            result = await tool.execute(table="bgp", hostname="R1")
            
            # Should catch and return error in ToolOutput
            assert isinstance(result, ToolOutput)
            assert result.error is not None
            assert "connection" in result.error.lower() or "cannot connect" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_strategy_handles_tool_error_gracefully(self, mock_llm):
        """Test strategy handles tool execution errors."""
        
        def mock_extraction(messages):
            return AIMessage(content="""{
                "tool": "suzieq_query",
                "parameters": {"hostname": "R1"},
                "confidence": 0.9,
                "reasoning": "Test error handling"
            }""")
        
        mock_llm.ainvoke = AsyncMock(side_effect=mock_extraction)
        
        strategy = FastPathStrategy(
            llm=mock_llm,
            tool_registry=ToolRegistry,
            confidence_threshold=0.7
        )
        
        # Execute with missing required parameter (will cause tool error)
        result = await strategy.execute("test query")
        
        # Strategy should catch tool error
        assert result["success"] is False
        assert result["reason"] == "exception"  # TypeError caught as exception
        assert "error" in result
        assert "table" in result["error"].lower()

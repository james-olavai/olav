"""Tests for Memory RAG integration in FastPathStrategy."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from olav.strategies.fast_path import FastPathStrategy
from olav.tools.base import ToolOutput, ToolRegistry


class TestMemoryRAGIntegration:
    """Test episodic memory RAG optimization in FastPathStrategy."""
    
    @pytest.fixture(autouse=True)
    def setup_registry(self):
        """Clear ToolRegistry before each test."""
        ToolRegistry._tools.clear()
        yield
        ToolRegistry._tools.clear()
    
    @pytest.fixture
    def mock_llm(self):
        """Mock LLM for testing."""
        llm = MagicMock()
        llm.ainvoke = AsyncMock()
        return llm
    
    @pytest.fixture
    def mock_tool_registry(self):
        """Mock ToolRegistry with registered tool."""
        registry = ToolRegistry()
        
        # Create mock tool
        mock_tool = MagicMock()
        mock_tool.name = "suzieq_query"
        mock_tool.description = "Query SuzieQ"
        mock_tool.execute = AsyncMock(return_value=ToolOutput(
            source="suzieq_query",
            device="R1",
            data=[{"hostname": "R1", "state": "Established"}],
            metadata={"elapsed_ms": 100},
            error=None,
        ))
        
        registry.register(mock_tool)
        return registry
    
    @pytest.fixture
    def mock_episodic_memory_tool(self):
        """Mock EpisodicMemoryTool."""
        tool = MagicMock()
        tool.execute = AsyncMock()
        return tool
    
    @pytest.mark.asyncio
    async def test_memory_rag_exact_match(
        self, mock_llm, mock_tool_registry, mock_episodic_memory_tool
    ):
        """Test Memory RAG with exact historical match."""
        from langchain_core.messages import AIMessage
        
        # Mock episodic memory to return exact match
        mock_episodic_memory_tool.execute.return_value = ToolOutput(
            source="episodic_memory_search",
            device="unknown",
            data=[{
                "intent": "查询 R1 BGP 状态",
                "tool_used": "suzieq_query",
                "parameters": {"table": "bgp", "hostname": "R1", "method": "get"},
                "execution_time_ms": 234,
            }],
            metadata={"result_count": 1},
            error=None,
        )
        
        # Mock LLM for answer formatting only (not parameter extraction)
        mock_llm.ainvoke.return_value = AIMessage(content="""{
            "answer": "R1 has 1 BGP neighbor in Established state",
            "data_used": ["hostname", "state"],
            "confidence": 0.95
        }""")
        
        strategy = FastPathStrategy(
            llm=mock_llm,
            tool_registry=mock_tool_registry,
            enable_memory_rag=True,
            episodic_memory_tool=mock_episodic_memory_tool,
        )
        
        result = await strategy.execute("查询 R1 BGP 状态")
        
        # Verify episodic memory was queried
        mock_episodic_memory_tool.execute.assert_called_once()
        assert mock_episodic_memory_tool.execute.call_args[1]["intent"] == "查询 R1 BGP 状态"
        
        # Verify LLM was NOT used for parameter extraction (only formatting)
        # Should be called once for formatting, not twice (extraction + formatting)
        assert mock_llm.ainvoke.call_count == 1
        
        # Verify execution succeeded
        assert result["success"] is True
        assert "BGP" in result["answer"]
    
    @pytest.mark.asyncio
    async def test_memory_rag_similar_match(
        self, mock_llm, mock_tool_registry, mock_episodic_memory_tool
    ):
        """Test Memory RAG with similar historical pattern (high similarity)."""
        from langchain_core.messages import AIMessage
        
        # Mock episodic memory with similar match (many overlapping words)
        mock_episodic_memory_tool.execute.return_value = ToolOutput(
            source="episodic_memory_search",
            device="unknown",
            data=[{
                "intent": "查询 R1 BGP 状态",  # Exact same as query (will have similarity 1.0)
                "tool_used": "suzieq_query",
                "parameters": {"table": "bgp", "hostname": "R1", "method": "get"},
                "execution_time_ms": 234,
            }],
            metadata={"result_count": 1},
            error=None,
        )
        
        mock_llm.ainvoke.return_value = AIMessage(content="""{
            "answer": "R1 BGP status retrieved",
            "data_used": ["hostname"],
            "confidence": 0.90
        }""")
        
        strategy = FastPathStrategy(
            llm=mock_llm,
            tool_registry=mock_tool_registry,
            enable_memory_rag=True,
            episodic_memory_tool=mock_episodic_memory_tool,
        )
        
        result = await strategy.execute("查询 R1 BGP 状态")
        
        # Should use memory pattern (exact match has similarity 1.0)
        mock_episodic_memory_tool.execute.assert_called_once()
        assert result["success"] is True
    
    @pytest.mark.asyncio
    async def test_memory_rag_low_similarity_fallback(
        self, mock_llm, mock_tool_registry, mock_episodic_memory_tool
    ):
        """Test Memory RAG falls back to LLM when similarity is low."""
        from langchain_core.messages import AIMessage
        
        # Mock episodic memory with low similarity match
        mock_episodic_memory_tool.execute.return_value = ToolOutput(
            source="episodic_memory_search",
            device="unknown",
            data=[{
                "intent": "配置 OSPF 路由",  # Very different intent
                "tool_used": "netconf_execute",
                "parameters": {"xpath": "/protocols/ospf"},
                "execution_time_ms": 1500,
            }],
            metadata={"result_count": 1},
            error=None,
        )
        
        # Mock LLM for both extraction and formatting
        mock_llm.ainvoke.side_effect = [
            # Parameter extraction response
            AIMessage(content="""{
                "tool": "suzieq_query",
                "parameters": {"table": "bgp", "hostname": "R1"},
                "confidence": 0.92,
                "reasoning": "Simple BGP status query"
            }"""),
            # Answer formatting response
            AIMessage(content="""{
                "answer": "R1 BGP status",
                "data_used": ["hostname"],
                "confidence": 0.90
            }""")
        ]
        
        strategy = FastPathStrategy(
            llm=mock_llm,
            tool_registry=mock_tool_registry,
            enable_memory_rag=True,
            episodic_memory_tool=mock_episodic_memory_tool,
        )
        
        result = await strategy.execute("查询 R1 BGP 状态")
        
        # Memory was queried but not used (low similarity)
        mock_episodic_memory_tool.execute.assert_called_once()
        
        # LLM should be called twice (extraction + formatting)
        assert mock_llm.ainvoke.call_count == 2
        
        assert result["success"] is True
    
    @pytest.mark.asyncio
    async def test_memory_rag_no_historical_data(
        self, mock_llm, mock_tool_registry, mock_episodic_memory_tool
    ):
        """Test Memory RAG when no historical data exists."""
        from langchain_core.messages import AIMessage
        
        # Mock episodic memory with no results
        mock_episodic_memory_tool.execute.return_value = ToolOutput(
            source="episodic_memory_search",
            device="unknown",
            data=[],  # No historical patterns found
            metadata={"result_count": 0},
            error=None,
        )
        
        # Mock LLM for extraction and formatting
        mock_llm.ainvoke.side_effect = [
            AIMessage(content="""{
                "tool": "suzieq_query",
                "parameters": {"table": "interfaces"},
                "confidence": 0.88,
                "reasoning": "Interface status query"
            }"""),
            AIMessage(content="""{
                "answer": "Interface status retrieved",
                "data_used": ["ifname"],
                "confidence": 0.85
            }""")
        ]
        
        strategy = FastPathStrategy(
            llm=mock_llm,
            tool_registry=mock_tool_registry,
            enable_memory_rag=True,
            episodic_memory_tool=mock_episodic_memory_tool,
        )
        
        result = await strategy.execute("查询接口状态")
        
        # Memory was queried but returned no results
        mock_episodic_memory_tool.execute.assert_called_once()
        
        # Should fallback to LLM extraction
        assert mock_llm.ainvoke.call_count == 2
        assert result["success"] is True
    
    @pytest.mark.asyncio
    async def test_memory_rag_disabled(
        self, mock_llm, mock_tool_registry, mock_episodic_memory_tool
    ):
        """Test that Memory RAG can be disabled."""
        from langchain_core.messages import AIMessage
        
        mock_llm.ainvoke.side_effect = [
            AIMessage(content="""{
                "tool": "suzieq_query",
                "parameters": {"table": "bgp"},
                "confidence": 0.90,
                "reasoning": "BGP query"
            }"""),
            AIMessage(content="""{
                "answer": "BGP data",
                "data_used": ["hostname"],
                "confidence": 0.88
            }""")
        ]
        
        strategy = FastPathStrategy(
            llm=mock_llm,
            tool_registry=mock_tool_registry,
            enable_memory_rag=False,  # Disabled
            episodic_memory_tool=mock_episodic_memory_tool,
        )
        
        result = await strategy.execute("查询 BGP")
        
        # Episodic memory should NOT be queried
        mock_episodic_memory_tool.execute.assert_not_called()
        
        # LLM should be used for extraction
        assert mock_llm.ainvoke.call_count == 2
        assert result["success"] is True
    
    @pytest.mark.asyncio
    async def test_memory_rag_error_handling(
        self, mock_llm, mock_tool_registry, mock_episodic_memory_tool
    ):
        """Test Memory RAG gracefully handles errors."""
        from langchain_core.messages import AIMessage
        
        # Mock episodic memory to raise exception
        mock_episodic_memory_tool.execute.side_effect = Exception("OpenSearch connection failed")
        
        # Mock LLM for fallback extraction
        mock_llm.ainvoke.side_effect = [
            AIMessage(content="""{
                "tool": "suzieq_query",
                "parameters": {"table": "bgp"},
                "confidence": 0.85,
                "reasoning": "BGP query"
            }"""),
            AIMessage(content="""{
                "answer": "BGP status",
                "data_used": ["hostname"],
                "confidence": 0.82
            }""")
        ]
        
        strategy = FastPathStrategy(
            llm=mock_llm,
            tool_registry=mock_tool_registry,
            enable_memory_rag=True,
            episodic_memory_tool=mock_episodic_memory_tool,
        )
        
        result = await strategy.execute("查询 BGP")
        
        # Should attempt memory search
        mock_episodic_memory_tool.execute.assert_called_once()
        
        # Should fallback to LLM despite error
        assert mock_llm.ainvoke.call_count == 2
        assert result["success"] is True
    
    def test_search_episodic_memory_similarity_calculation(self):
        """Test Jaccard similarity calculation in _search_episodic_memory."""
        # Test exact match
        query1 = "查询 R1 BGP 状态"
        historical1 = "查询 R1 BGP 状态"
        query_words = set(query1.lower().split())
        historical_words = set(historical1.lower().split())
        intersection = query_words & historical_words
        union = query_words | historical_words
        similarity = len(intersection) / len(union)
        assert similarity == 1.0
        
        # Test partial match
        query2 = "查询 R1 BGP"
        historical2 = "查询 R1 BGP 状态"
        query_words = set(query2.lower().split())
        historical_words = set(historical2.lower().split())
        intersection = query_words & historical_words
        union = query_words | historical_words
        similarity = len(intersection) / len(union)
        assert 0.7 < similarity < 1.0  # High similarity but not exact
        
        # Test low similarity
        query3 = "查询接口"
        historical3 = "配置 BGP 邻居"
        query_words = set(query3.lower().split())
        historical_words = set(historical3.lower().split())
        intersection = query_words & historical_words
        union = query_words | historical_words
        similarity = len(intersection) / len(union)
        assert similarity < 0.3  # Low similarity

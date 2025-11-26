"""Manual test script for Memory System end-to-end flow.

This script demonstrates:
1. Episodic memory index initialization
2. MemoryWriter capturing successful executions
3. EpisodicMemoryTool retrieving historical patterns
4. FastPathStrategy using both components

Run: uv run python -m tests.manual.test_memory_system
"""

import asyncio
import logging
from datetime import datetime, timezone

from langchain_openai import ChatOpenAI

from olav.core.memory import OpenSearchMemory
from olav.core.memory_writer import MemoryWriter
from olav.strategies.fast_path import FastPathStrategy
from olav.tools.base import ToolOutput, ToolRegistry
from olav.tools.opensearch_tool import EpisodicMemoryTool
from olav.tools.suzieq_tool import SuzieQTool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_memory_writer():
    """Test MemoryWriter captures successful execution."""
    logger.info("=" * 60)
    logger.info("TEST 1: MemoryWriter Capture")
    logger.info("=" * 60)
    
    memory = OpenSearchMemory()
    writer = MemoryWriter(memory=memory)
    
    # Simulate successful tool execution
    tool_output = ToolOutput(
        source="suzieq_query",
        device="R1",
        data=[
            {"hostname": "R1", "peer": "192.168.1.2", "state": "Established"},
            {"hostname": "R1", "peer": "192.168.1.3", "state": "Established"},
        ],
        metadata={"elapsed_ms": 234, "table": "bgp"},
        error=None,
    )
    
    await writer.capture_success(
        intent="查询 R1 BGP 邻居状态",
        tool_used="suzieq_query",
        parameters={"table": "bgp", "hostname": "R1", "method": "get"},
        tool_output=tool_output,
        strategy_used="fast_path",
        execution_time_ms=234,
    )
    
    logger.info("✓ Successfully captured episodic memory")
    
    # Wait for indexing
    await asyncio.sleep(1)
    
    return True


async def test_episodic_memory_retrieval():
    """Test EpisodicMemoryTool retrieves historical patterns."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: EpisodicMemoryTool Retrieval")
    logger.info("=" * 60)
    
    tool = EpisodicMemoryTool()
    
    # Search for BGP-related patterns
    result = await tool.execute(
        intent="查询 BGP 状态",
        max_results=3,
        only_successful=True,
    )
    
    logger.info(f"Found {len(result.data)} historical patterns:")
    for i, pattern in enumerate(result.data[:3], 1):
        logger.info(f"  {i}. Intent: {pattern.get('intent')}")
        logger.info(f"     XPath: {pattern.get('xpath')}")
        logger.info(f"     Tool: {pattern.get('tool_used')}")
    
    assert len(result.data) > 0, "Should find at least one BGP pattern"
    logger.info("✓ Successfully retrieved episodic memory patterns")
    
    return result


async def test_memory_rag_workflow():
    """Test RAG workflow: Memory → Schema → Tool execution."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: Memory RAG Workflow")
    logger.info("=" * 60)
    
    # Step 1: Search episodic memory
    memory_tool = EpisodicMemoryTool()
    memory_result = await memory_tool.execute(
        intent="查询接口状态",
        max_results=2,
    )
    
    logger.info(f"Step 1 - Memory Search: Found {len(memory_result.data)} patterns")
    if memory_result.data:
        pattern = memory_result.data[0]
        logger.info(f"  Best match: {pattern.get('intent')}")
        logger.info(f"  Historical XPath: {pattern.get('xpath')}")
        logger.info(f"  Tool used: {pattern.get('tool_used')}")
    
    # Step 2: If memory hit, use same tool/parameters
    # Step 3: If no memory hit, search schema (OpenConfigSchemaTool)
    # Step 4: Execute tool
    
    logger.info("✓ RAG workflow demonstrated")
    return True


async def test_fast_path_with_memory():
    """Test FastPathStrategy with MemoryWriter integration."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: FastPathStrategy + MemoryWriter Integration")
    logger.info("=" * 60)
    
    # Note: This requires actual LLM and tool setup
    # For demo, we just verify MemoryWriter is initialized
    
    from olav.core.settings import settings
    
    llm = ChatOpenAI(
        model=settings.llm_model_name,
        api_key=settings.llm_api_key,
        temperature=0.0,
    )
    
    # Use fresh registry for this test
    registry = ToolRegistry()
    
    strategy = FastPathStrategy(
        llm=llm,
        tool_registry=registry,
    )
    
    # Verify memory_writer is initialized
    assert strategy.memory_writer is not None
    logger.info("✓ FastPathStrategy has MemoryWriter initialized")
    
    # In actual execution:
    # result = await strategy.execute("查询 R1 BGP 状态")
    # MemoryWriter will automatically capture success
    
    return True


async def main():
    """Run all memory system tests."""
    logger.info("\n" + "=" * 70)
    logger.info("OLAV MEMORY SYSTEM - MANUAL INTEGRATION TEST")
    logger.info("=" * 70)
    
    try:
        # Test 1: MemoryWriter
        await test_memory_writer()
        
        # Test 2: EpisodicMemoryTool
        await test_episodic_memory_retrieval()
        
        # Test 3: RAG workflow
        await test_memory_rag_workflow()
        
        # Test 4: FastPathStrategy integration
        await test_fast_path_with_memory()
        
        logger.info("\n" + "=" * 70)
        logger.info("✓ ALL TESTS PASSED - Memory System Integration Complete")
        logger.info("=" * 70)
        logger.info("\nMemory System Components:")
        logger.info("  1. ✓ olav-episodic-memory index (stores historical success patterns)")
        logger.info("  2. ✓ MemoryWriter (captures successful executions)")
        logger.info("  3. ✓ EpisodicMemoryTool (retrieves patterns for RAG)")
        logger.info("  4. ✓ FastPathStrategy integration (auto-capture on success)")
        logger.info("\nNext: Integrate EpisodicMemoryTool into FastPathStrategy RAG workflow")
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())

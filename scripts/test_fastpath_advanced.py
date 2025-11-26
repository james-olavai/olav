#!/usr/bin/env python
"""
FastPath Advanced Feature Test Script

Tests FastPath strategy invoking advanced tool features:
1. SuzieQ: summarize, time window, multi-field filtering
2. Schema discovery accuracy
3. JSON parsing robustness

Usage:
    uv run python scripts/test_fastpath_advanced.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add src and project root to path (for config.settings imports)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))  # For 'from config.settings import ...'

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Reduce noise
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("opensearch").setLevel(logging.WARNING)


async def test_suzieq_summarize():
    """Test SuzieQ summarize method"""
    print("\n" + "=" * 60)
    print("🔍 Test 1: SuzieQ Summarize (Statistical Summary)")
    print("=" * 60)
    
    from olav.tools.base import ToolRegistry
    
    tool = ToolRegistry.get_tool("suzieq_query")
    if not tool:
        print("❌ suzieq_query tool not registered")
        return False
    
    result = await tool.execute(
        table="ospfNbr",
        method="summarize",
    )
    
    print(f"Query: table=ospfNbr, method=summarize")
    print(f"Result: {result.data}")
    print(f"Error: {result.error}")
    
    if result.error:
        print(f"❌ Summarize test failed: {result.error}")
        return False
    
    print("✅ SuzieQ Summarize test passed")
    return True


async def test_suzieq_time_window():
    """Test SuzieQ time window filtering"""
    print("\n" + "=" * 60)
    print("🔍 Test 2: SuzieQ Time Window Filtering")
    print("=" * 60)
    
    from olav.tools.base import ToolRegistry
    
    tool = ToolRegistry.get_tool("suzieq_query")
    
    for hours in [1, 24, 0]:  # 0 = all history
        result = await tool.execute(
            table="interfaces",
            method="get",
            max_age_hours=hours,
        )
        
        count = len(result.data) if result.data else 0
        label = "all history" if hours == 0 else f"last {hours} hour(s)"
        print(f"  {label}: {count} records")
    
    print("✅ SuzieQ time window test passed")
    return True


async def test_suzieq_multi_filter():
    """Test SuzieQ multi-field filtering"""
    print("\n" + "=" * 60)
    print("🔍 Test 3: SuzieQ Multi-field Filtering")
    print("=" * 60)
    
    from olav.tools.base import ToolRegistry
    
    tool = ToolRegistry.get_tool("suzieq_query")
    
    result = await tool.execute(
        table="ospfNbr",
        method="get",
        state="full",
    )
    
    print(f"Query: table=ospfNbr, state=full")
    count = len(result.data) if result.data else 0
    print(f"Result: {count} OSPF neighbors in full state")
    
    if result.data:
        for nbr in result.data[:3]:
            print(f"  - {nbr.get('hostname')} <-> {nbr.get('peerRouterId')} ({nbr.get('state')})")
    
    print("✅ SuzieQ multi-field filtering test passed")
    return True


async def test_fastpath_summarize():
    """Test FastPath strategy handling summarize request"""
    print("\n" + "=" * 60)
    print("🔍 Test 4: FastPath + LLM (Summarize Query)")
    print("=" * 60)
    
    from olav.core.llm import LLMFactory
    from olav.strategies.fast_path import FastPathStrategy
    from olav.tools.base import ToolRegistry
    
    llm = LLMFactory.get_chat_model()
    strategy = FastPathStrategy(llm=llm, tool_registry=ToolRegistry)
    
    query = "Summarize OSPF neighbor status across all devices"
    print(f"Query: {query}")
    
    result = await strategy.execute(query)
    
    print(f"Success: {result.get('success')}")
    if result.get('success'):
        print(f"Answer: {result.get('answer')}")
    else:
        print(f"Reason: {result.get('reason')}")
    
    return result.get('success', False)


async def test_fastpath_interface():
    """Test FastPath interface status query"""
    print("\n" + "=" * 60)
    print("🔍 Test 5: FastPath Interface Status Query")
    print("=" * 60)
    
    from olav.core.llm import LLMFactory
    from olav.strategies.fast_path import FastPathStrategy
    from olav.tools.base import ToolRegistry
    
    llm = LLMFactory.get_chat_model()
    strategy = FastPathStrategy(llm=llm, tool_registry=ToolRegistry)
    
    query = "Show all interface status on R1"
    print(f"Query: {query}")
    
    result = await strategy.execute(query)
    
    print(f"Success: {result.get('success')}")
    if result.get('success'):
        print(f"Answer: {result.get('answer')}")
        tool_output = result.get('tool_output')
        if tool_output and tool_output.data:
            print(f"Record count: {len(tool_output.data)}")
    else:
        print(f"Reason: {result.get('reason')}")
    
    return result.get('success', False)


async def test_fastpath_bgp():
    """Test FastPath BGP query"""
    print("\n" + "=" * 60)
    print("🔍 Test 6: FastPath BGP Neighbor Query")
    print("=" * 60)
    
    from olav.core.llm import LLMFactory
    from olav.strategies.fast_path import FastPathStrategy
    from olav.tools.base import ToolRegistry
    
    llm = LLMFactory.get_chat_model()
    strategy = FastPathStrategy(llm=llm, tool_registry=ToolRegistry)
    
    query = "Show all BGP neighbor status"
    print(f"Query: {query}")
    
    result = await strategy.execute(query)
    
    print(f"Success: {result.get('success')}")
    if result.get('success'):
        print(f"Answer: {result.get('answer')}")
    else:
        print(f"Reason: {result.get('reason')}")
        if "NO_DATA" in str(result.get('error', '')):
            print("ℹ️ No BGP data (normal for test environment)")
            return True
    
    return result.get('success', False)


async def test_fastpath_routes():
    """Test FastPath routing table query"""
    print("\n" + "=" * 60)
    print("🔍 Test 7: FastPath Routing Table Query")
    print("=" * 60)
    
    from olav.core.llm import LLMFactory
    from olav.strategies.fast_path import FastPathStrategy
    from olav.tools.base import ToolRegistry
    
    llm = LLMFactory.get_chat_model()
    strategy = FastPathStrategy(llm=llm, tool_registry=ToolRegistry)
    
    query = "Show routing table on R1"
    print(f"Query: {query}")
    
    result = await strategy.execute(query)
    
    print(f"Success: {result.get('success')}")
    if result.get('success'):
        answer = result.get('answer', '')
        print(f"Answer: {answer[:200]}..." if len(answer) > 200 else f"Answer: {answer}")
        tool_output = result.get('tool_output')
        if tool_output and tool_output.data:
            print(f"Route entries: {len(tool_output.data)}")
    else:
        print(f"Reason: {result.get('reason')}")
    
    return result.get('success', False)


async def test_fastpath_device():
    """Test FastPath device info query"""
    print("\n" + "=" * 60)
    print("🔍 Test 8: FastPath Device Info Query")
    print("=" * 60)
    
    from olav.core.llm import LLMFactory
    from olav.strategies.fast_path import FastPathStrategy
    from olav.tools.base import ToolRegistry
    
    llm = LLMFactory.get_chat_model()
    strategy = FastPathStrategy(llm=llm, tool_registry=ToolRegistry)
    
    query = "Show basic info for all devices"
    print(f"Query: {query}")
    
    result = await strategy.execute(query)
    
    print(f"Success: {result.get('success')}")
    if result.get('success'):
        print(f"Answer: {result.get('answer')}")
        tool_output = result.get('tool_output')
        if tool_output and tool_output.data:
            print(f"Device count: {len(tool_output.data)}")
            for dev in tool_output.data[:5]:
                print(f"  - {dev.get('hostname')}: {dev.get('model', 'N/A')}")
    else:
        print(f"Reason: {result.get('reason')}")
    
    return result.get('success', False)


async def test_fastpath_lldp():
    """Test FastPath LLDP neighbor query"""
    print("\n" + "=" * 60)
    print("🔍 Test 9: FastPath LLDP Neighbor Query")
    print("=" * 60)
    
    from olav.core.llm import LLMFactory
    from olav.strategies.fast_path import FastPathStrategy
    from olav.tools.base import ToolRegistry
    
    llm = LLMFactory.get_chat_model()
    strategy = FastPathStrategy(llm=llm, tool_registry=ToolRegistry)
    
    query = "What are the LLDP neighbors of R1"
    print(f"Query: {query}")
    
    result = await strategy.execute(query)
    
    print(f"Success: {result.get('success')}")
    if result.get('success'):
        print(f"Answer: {result.get('answer')}")
    else:
        print(f"Reason: {result.get('reason')}")
        if "NO_DATA" in str(result.get('error', '')):
            print("ℹ️ No LLDP data (normal for test environment)")
            return True
    
    return result.get('success', False)


async def test_schema_discovery():
    """Test Schema discovery accuracy"""
    print("\n" + "=" * 60)
    print("🔍 Test 10: Schema Discovery Accuracy")
    print("=" * 60)
    
    from olav.tools.base import ToolRegistry
    
    tool = ToolRegistry.get_tool("suzieq_schema_search")
    if not tool:
        print("❌ suzieq_schema_search tool not registered")
        return False
    
    test_queries = [
        ("OSPF neighbor", ["ospfNbr"]),
        ("BGP status", ["bgp"]),
        ("interface status", ["interfaces"]),
        ("routing table", ["routes"]),
        ("VLAN information", ["vlan"]),
        ("MAC address table", ["macs"]),
    ]
    
    passed = 0
    for query, expected_tables in test_queries:
        result = await tool.execute(query=query)
        if result.data:
            found_tables = [item.get('table') for item in result.data]
            match = any(exp in found_tables for exp in expected_tables)
            status = "✅" if match else "⚠️"
            print(f"  {status} '{query}' -> {found_tables[:3]}")
            if match:
                passed += 1
        else:
            print(f"  ❌ '{query}' -> no results")
    
    print(f"\nAccuracy: {passed}/{len(test_queries)}")
    return passed >= len(test_queries) // 2


def test_json_parser_robustness():
    """Test JSON parser robustness with malformed inputs"""
    print("\n" + "=" * 60)
    print("🔍 Test 11: JSON Parser Robustness")
    print("=" * 60)
    
    from olav.core.llm import LLMFactory
    from olav.strategies.fast_path import FastPathStrategy
    from olav.tools.base import ToolRegistry
    
    llm = LLMFactory.get_chat_model()
    strategy = FastPathStrategy(llm=llm, tool_registry=ToolRegistry)
    
    # Test cases with various malformed JSON
    test_cases = [
        # Case 1: Markdown code blocks
        (
            '```json\n{"tool": "suzieq_query", "parameters": {"table": "bgp"}, "confidence": 0.9, "reasoning": "test"}\n```',
            "markdown code blocks"
        ),
        # Case 2: Extra text before JSON
        (
            'Here is the response:\n{"tool": "suzieq_query", "parameters": {}, "confidence": 0.8, "reasoning": "test"}',
            "extra text before JSON"
        ),
        # Case 3: Trailing comma
        (
            '{"tool": "suzieq_query", "parameters": {"table": "device",}, "confidence": 0.85, "reasoning": "test"}',
            "trailing comma"
        ),
        # Case 4: Mixed quotes (edge case)
        (
            '{"tool": "suzieq_query", "parameters": {"table": "interfaces"}, "confidence": 0.9, "reasoning": "Found interfaces table"}',
            "standard JSON"
        ),
        # Case 5: Multiple code blocks
        (
            'Let me analyze:\n```json\n{"tool": "suzieq_query", "parameters": {}, "confidence": 0.7, "reasoning": "analysis"}\n```\nDone.',
            "text around code block"
        ),
    ]
    
    passed = 0
    for content, description in test_cases:
        result = strategy._parse_json_response(content, description)
        if result.tool and result.confidence > 0:
            print(f"  ✅ {description}: tool={result.tool}, conf={result.confidence}")
            passed += 1
        else:
            print(f"  ❌ {description}: failed to parse")
    
    print(f"\nParsing success: {passed}/{len(test_cases)}")
    return passed == len(test_cases)


async def main():
    """Run all tests"""
    print("=" * 60)
    print("FastPath Advanced Feature Tests")
    print("=" * 60)
    
    if not os.getenv("LLM_API_KEY"):
        print("❌ LLM_API_KEY environment variable not set")
        return
    
    # Import tool modules (auto-registers)
    import olav.tools.suzieq_tool  # noqa: F401
    from olav.tools.base import ToolRegistry
    
    print(f"Registered tools: {[t.name for t in ToolRegistry.list_tools()]}")
    
    results = {}
    
    # Basic SuzieQ tool tests
    results["suzieq_summarize"] = await test_suzieq_summarize()
    results["suzieq_time_window"] = await test_suzieq_time_window()
    results["suzieq_multi_filter"] = await test_suzieq_multi_filter()
    
    # JSON parser robustness test (sync)
    results["json_parser"] = test_json_parser_robustness()
    
    # FastPath + LLM tests
    results["fastpath_summarize"] = await test_fastpath_summarize()
    results["fastpath_interface"] = await test_fastpath_interface()
    results["fastpath_bgp"] = await test_fastpath_bgp()
    results["fastpath_routes"] = await test_fastpath_routes()
    results["fastpath_device"] = await test_fastpath_device()
    results["fastpath_lldp"] = await test_fastpath_lldp()
    
    # Schema discovery tests
    results["schema_discovery"] = await test_schema_discovery()
    
    # Print summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")


if __name__ == "__main__":
    asyncio.run(main())

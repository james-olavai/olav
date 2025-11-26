#!/usr/bin/env python
"""Simple OSPF neighbor query test with real LLM."""

import asyncio
import sys

# Windows asyncio fix
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def test_ospf_query():
    """Test OSPF neighbor query using SuzieQ tool."""
    from olav.tools.suzieq_parquet_tool import suzieq_query, suzieq_schema_search
    
    print("=" * 60)
    print("🔍 测试 1: 查询 SuzieQ Schema (OSPF 相关表)")
    print("=" * 60)
    
    # First, check schema
    schema_result = await suzieq_schema_search.ainvoke({"query": "ospf neighbor"})
    print(f"Schema 结果:\n{schema_result}\n")
    
    print("=" * 60)
    print("🔍 测试 2: 查询 OSPF 邻居状态 (ospfNbr 表)")
    print("=" * 60)
    
    # Query OSPF neighbors using correct table name
    result = await suzieq_query.ainvoke({
        "table": "ospfNbr",
        "columns": ["hostname", "peerRouterId", "peerIP", "state", "ifname", "area"],
        "view": "latest",
    })
    print(f"OSPF 邻居:\n{result}\n")
    
    print("=" * 60)
    print("🔍 测试 3: 查询特定设备 R1 的 OSPF 邻居")
    print("=" * 60)
    
    result_r1 = await suzieq_query.ainvoke({
        "table": "ospfNbr",
        "hostname": "R1",
        "columns": ["hostname", "peerRouterId", "peerIP", "state", "ifname", "area"],
        "view": "latest",
    })
    print(f"R1 OSPF 邻居:\n{result_r1}\n")
    
    print("=" * 60)
    print("✅ 基础 SuzieQ 工具测试完成")
    print("=" * 60)


async def test_strategy_selection():
    """Test strategy selection for OSPF query."""
    from olav.core.llm import LLMFactory
    from olav.strategies import StrategySelector
    
    print("\n" + "=" * 60)
    print("🧠 测试 4: Strategy Selector (规则 + LLM 路由)")
    print("=" * 60)
    
    llm = LLMFactory.get_chat_model()
    selector = StrategySelector(llm=llm, use_llm_fallback=True)  # 启用 LLM fallback
    
    queries = [
        "查询 R1 的 OSPF 邻居状态",
        "为什么 R1 的 OSPF 邻居不起来？",
        "审计所有路由器的 OSPF 配置",
    ]
    
    for query in queries:
        decision = await selector.select(query)  # 使用 async 方法
        print(f"\n查询: {query}")
        print(f"  策略: {decision.strategy}")
        print(f"  置信度: {decision.confidence:.2f}")
        print(f"  理由: {decision.reasoning}")
    
    print("\n" + "=" * 60)
    print("✅ Strategy Selector 测试完成")
    print("=" * 60)


async def test_full_llm_execution():
    """Test full LLM execution with FastPath strategy."""
    import logging
    logging.basicConfig(level=logging.DEBUG)
    
    from olav.core.llm import LLMFactory
    from olav.strategies.fast_path import FastPathStrategy
    from olav.tools.base import ToolRegistry
    
    # Import tool modules to trigger registration
    import olav.tools.suzieq_tool  # noqa: F401
    import olav.tools.opensearch_tool  # noqa: F401
    
    print("\n" + "=" * 60)
    print("🚀 测试 5: FastPath 策略 + 真实 LLM 执行")
    print("=" * 60)
    
    # List registered tools
    tools = ToolRegistry.list_tools()
    print(f"已注册工具: {[t.name for t in tools]}")
    
    llm = LLMFactory.get_chat_model()
    
    # Create FastPath strategy with tool registry
    strategy = FastPathStrategy(
        llm=llm,
        tool_registry=ToolRegistry,
    )
    
    query = "查询 R1 的 OSPF 邻居状态"
    print(f"\n用户查询: {query}")
    print("-" * 40)
    
    result = await strategy.execute(query)
    
    print(f"\n===== 完整返回结果 =====")
    import json
    # 处理不可序列化对象
    def serialize(obj):
        if hasattr(obj, '__dict__'):
            return str(obj)
        return obj
    try:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=serialize))
    except:
        print(result)
    print("=" * 40)
    
    print(f"\n执行结果:")
    print(f"  成功: {result.get('success', False)}")
    
    if result.get('success'):
        print(f"  答案: {result.get('answer', 'N/A')}")
        metadata = result.get('metadata', {})
        print(f"  使用工具: {metadata.get('tool', 'N/A')}")
        print(f"  置信度: {metadata.get('confidence', 0):.2f}")
        
        # 打印工具输出
        tool_output = result.get('tool_output')
        if tool_output:
            print(f"\n===== 工具输出 =====")
            print(f"  source: {getattr(tool_output, 'source', 'N/A')}")
            print(f"  device: {getattr(tool_output, 'device', 'N/A')}")
            print(f"  data: {getattr(tool_output, 'data', 'N/A')}")
            print(f"  error: {getattr(tool_output, 'error', 'N/A')}")
    else:
        print(f"  失败原因: {result.get('reason', 'unknown')}")
        print(f"  错误: {result.get('error', 'N/A')}")
    
    print("\n" + "=" * 60)
    print("✅ FastPath 策略执行测试完成")
    print("=" * 60)


async def main():
    """Run all tests."""
    print("\n🎯 OLAV OSPF 邻居查询测试 (真实 LLM)\n")
    
    # Test 1-3: Basic SuzieQ tools (no LLM)
    await test_ospf_query()
    
    # Test 4: Strategy selection with LLM
    try:
        await test_strategy_selection()
    except Exception as e:
        print(f"⚠️ Strategy Selector 测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 5: Full LLM execution
    try:
        await test_full_llm_execution()
    except Exception as e:
        print(f"⚠️ FastPath 执行测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n🎉 所有测试完成!")


if __name__ == "__main__":
    asyncio.run(main())

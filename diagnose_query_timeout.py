#!/usr/bin/env python3
"""诊断查询超时问题 - List IP addresses on R3"""

import asyncio
import time
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_orchestrator_query():
    """测试orchestrator查询执行时间"""
    
    print("🧪 诊断Orchestrator查询超时")
    print("=" * 70)
    print("\n📝 测试查询: 'list all ip addresses on R3'")
    print("预期: 快速从数据库查询IP地址配置\n")
    
    from src.olav.agents.router import create_orchestrator
    from langchain_core.messages import HumanMessage
    
    query = "list all ip addresses on R3"
    
    # Test 1: 测试Orchestrator创建时间
    print("\n[TEST 1] Orchestrator创建时间...")
    start = time.time()
    try:
        agent = create_orchestrator()
        elapsed = time.time() - start
        print(f"✅ Orchestrator创建成功: {elapsed:.2f}s")
    except Exception as e:
        print(f"❌ Orchestrator创建失败: {e}")
        return
    
    # Test 2: 测试ag ent.ainvoke()超时
    print("\n[TEST 2] agent.ainvoke()执行时间 (timeout=10s)...")
    inputs = {"messages": [HumanMessage(content=query)]}
    config = {"configurable": {"thread_id": "test-diag-123"}}
    
    start = time.time()
    try:
        # 使用较短的超时时间测试
        final_state = await asyncio.wait_for(
            agent.ainvoke(inputs, config=config),
            timeout=10.0,  # 10秒超时（而不是180秒）
        )
        elapsed = time.time() - start
        print(f"✅ agent.ainvoke()完成: {elapsed:.2f}s")
        
        result = final_state.get("result")
        if result:
            print(f"   结果: {str(result)[:100]}...")
        
    except asyncio.TimeoutError:
        elapsed = time.time() - start
        print(f"⏱️ agent.ainvoke()超时 ({elapsed:.1f}s之后)")
        print("   💡 原因分析:")
        print("      - DeepAgents async可能有问题")
        print("      - SubAgent执行很慢")
        print("      - LLM调用被阻塞")
        
    except Exception as e:
        elapsed = time.time() - start
        print(f"❌ agent.ainvoke()错误 ({elapsed:.1f}s): {type(e).__name__}: {e}")
    
    print("\n" + "=" * 70)
    print("建议:")
    print("1. 如果ainvoke()本身超时: 可能是DeepAgents async问题")
    print("2. 如果快速返回但结果错误: 可能是查询逻辑问题")
    print("3. 检查LLM API调用是否很慢")

async def main():
    await test_orchestrator_query()

if __name__ == "__main__":
    asyncio.run(main())

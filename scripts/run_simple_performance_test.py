"""
Phase 4.2 - 简化性能基准测试（直接 LLM 测试）

重点：测量 LLM 调用响应时间，而不是完整的 Agent 框架

运行:
    uv run python scripts/run_simple_performance_test.py
"""

import asyncio
import time
import statistics
import json
from pathlib import Path
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


async def test_llm_performance():
    """Test direct LLM provider response time"""
    from config.settings import settings
    from olav.core.llm import LLMFactory
    
    logger.info("""
╔════════════════════════════════════════════════════════════╗
║      OLAV v2.0 LLM 性能基准 (Phase 4.2)                   ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    # Initialize LLM from .env config
    llm = LLMFactory.get_chat_model(temperature=0.1)
    
    logger.info(f"📊 LLM 配置:")
    logger.info(f"   Provider: {settings.llm_provider}")
    logger.info(f"   Model: {settings.llm_model_name}")
    if settings.llm_base_url:
        logger.info(f"   Endpoint: {settings.llm_base_url}")
    
    # Test queries
    queries = [
        "Hello, what is your name?",
        "Can you list your capabilities?",
        "How do you process network queries?",
    ]
    
    logger.info("\n" + "="*60)
    logger.info("📊 基准 1: 单个 LLM 调用响应时间")
    logger.info("="*60)
    
    times = []
    
    # Warmup
    logger.info("▶️  预热...")
    for _ in range(2):
        try:
            await llm.ainvoke([{"role": "user", "content": "Hello"}])
        except Exception:
            pass
    
    # Test
    logger.info(f"▶️  执行 {len(queries)} 个查询...")
    for i, query in enumerate(queries):
        start = time.time()
        try:
            result = await llm.ainvoke([{"role": "user", "content": query}])
            elapsed = time.time() - start
            times.append(elapsed)
            logger.info(f"  [{i+1}/{len(queries)}] {elapsed:.3f}s | {query[:40]}...")
        except Exception as e:
            logger.error(f"  [{i+1}/{len(queries)}] ❌ {str(e)[:60]}")
    
    # Statistics
    if times:
        stats = {
            "min": min(times),
            "max": max(times),
            "mean": statistics.mean(times),
            "median": statistics.median(times),
        }
        
        logger.info(f"\n✅ 结果:")
        logger.info(f"   最小: {stats['min']:.3f}s")
        logger.info(f"   最大: {stats['max']:.3f}s")
        logger.info(f"   平均: {stats['mean']:.3f}s")
        logger.info(f"   中位: {stats['median']:.3f}s")
        
        # Check target
        if stats['mean'] < 5.0:
            logger.info(f"   ✅ 目标达成 (< 5.0s)")
        else:
            logger.warning(f"   ⚠️  目标未达成 (< 5.0s)")
        
        return stats
    else:
        logger.error("❌ 所有查询失败")
        return {}


async def test_concurrent_llm_calls():
    """Test concurrent LLM calls"""
    from olav.core.llm import LLMFactory
    
    logger.info("\n" + "="*60)
    logger.info("📊 基准 2: 并发 LLM 调用 (5 个并发)")
    logger.info("="*60)
    
    llm = LLMFactory.get_chat_model(temperature=0.1)
    
    async def single_call(index: int):
        start = time.time()
        try:
            await llm.ainvoke([{"role": "user", "content": f"Query {index}: What are you?"}])
            return time.time() - start
        except Exception as e:
            logger.error(f"  Call {index} failed: {str(e)[:60]}")
            return None
    
    logger.info("▶️  执行 5 个并发调用...")
    start_total = time.time()
    tasks = [single_call(i) for i in range(5)]
    results = await asyncio.gather(*tasks)
    total_time = time.time() - start_total
    
    # Filter out failures
    times = [t for t in results if t is not None]
    
    if times:
        logger.info(f"\n✅ 结果:")
        logger.info(f"   总耗时: {total_time:.3f}s")
        logger.info(f"   平均单个调用: {statistics.mean(times):.3f}s")
        logger.info(f"   吞吐量: {len(times)/total_time:.2f} calls/sec")
        logger.info(f"   成功率: {len(times)}/{len(tasks)}")
        
        return {
            "total_time": total_time,
            "individual_mean": statistics.mean(times),
            "throughput": len(times) / total_time,
        }
    else:
        logger.error("❌ 所有并发调用失败")
        return {}


async def main():
    """Run performance tests"""
    try:
        results = {
            "timestamp": datetime.now().isoformat(),
            "version": "2.0.0",
            "tests": {}
        }
        
        # Test 1: Single LLM calls
        stats = await test_llm_performance()
        if stats:
            results["tests"]["llm_single_call"] = stats
        
        # Test 2: Concurrent LLM calls
        concurrent_stats = await test_concurrent_llm_calls()
        if concurrent_stats:
            results["tests"]["concurrent_llm_calls"] = concurrent_stats
        
        # Save results
        output_file = Path("exports/benchmarks") / f"llm_performance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"\n💾 结果已保存: {output_file}")
        logger.info("\n" + "="*60)
        logger.info("✅ 性能基准测试完成")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())

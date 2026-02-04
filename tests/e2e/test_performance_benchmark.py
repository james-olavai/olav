"""
Performance Benchmark E2E Tests (TDD - Phase 4.2)
性能基准测试
"""

import pytest
import time
import asyncio
from langchain_core.messages import HumanMessage


@pytest.mark.benchmark
class TestSimpleQueryPerformance:
    """简单查询性能测试"""

    @pytest.mark.asyncio
    async def test_simple_query_performance(self):
        """基准测试: 简单查询 - RED状态 (待优化)"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        start = time.time()
        await orchestrator.ainvoke({
            "messages": [HumanMessage(content="列出设备")]
        })
        duration = time.time() - start

        # 验收标准: 简单查询应在2秒内完成
        assert duration < 2.0, f"查询耗时{duration:.2f}秒，超过2秒基准"

    @pytest.mark.asyncio
    async def test_database_query_latency(self):
        """测试数据库查询延迟"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        start = time.time()
        await orchestrator.ainvoke({
            "messages": [HumanMessage(content="查询R1的接口列表")]
        })
        duration = time.time() - start

        assert duration < 3.0, f"数据库查询耗时{duration:.2f}秒"


@pytest.mark.benchmark
class TestComplexQueryPerformance:
    """复杂查询性能测试"""

    @pytest.mark.asyncio
    async def test_complex_query_performance(self):
        """基准测试: 复杂查询 - RED状态 (待优化)"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        start = time.time()
        await orchestrator.ainvoke({
            "messages": [HumanMessage(
                content="分析所有核心设备的性能问题并提供优化建议"
            )]
        })
        duration = time.time() - start

        # 验收标准: 复杂查询应在5秒内完成
        assert duration < 5.0, f"复杂查询耗时{duration:.2f}秒，超过5秒基准"

    @pytest.mark.asyncio
    async def test_multi_step_query_performance(self):
        """测试多步骤查询性能"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        start = time.time()
        await orchestrator.ainvoke({
            "messages": [HumanMessage(
                content="1. 查询所有设备 2. 检查BGP状态 3. 分析异常"
            )]
        })
        duration = time.time() - start

        assert duration < 8.0, f"多步骤查询耗时{duration:.2f}秒"


@pytest.mark.benchmark
class TestConcurrentPerformance:
    """并发性能测试"""

    @pytest.mark.asyncio
    async def test_concurrent_queries(self):
        """基准测试: 并发查询 - RED状态 (待优化)"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        queries = [
            "查询R1状态",
            "列出所有接口",
            "检查CPU使用率",
        ]

        start = time.time()
        await asyncio.gather(*[
            orchestrator.ainvoke({"messages": [HumanMessage(content=q)]})
            for q in queries
        ])
        duration = time.time() - start

        # 验收标准: 并发3个查询应在6秒内完成 (不是3x单次)
        assert duration < 6.0, f"并发查询耗时{duration:.2f}秒，超过6秒"

    @pytest.mark.asyncio
    async def test_high_concurrency(self):
        """测试高并发场景 - 10个并发查询"""
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        queries = [f"查询设备{i}的状态" for i in range(10)]

        start = time.time()
        results = await asyncio.gather(*[
            orchestrator.ainvoke({"messages": [HumanMessage(content=q)]})
            for q in queries
        ], return_exceptions=True)
        duration = time.time() - start

        # 验收标准: 10个并发查询应在15秒内完成
        assert duration < 15.0, f"10并发查询耗时{duration:.2f}秒"

        # 检查成功率
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        success_rate = success_count / len(results)
        assert success_rate > 0.9, f"并发成功率{success_rate:.1%}，低于90%"


@pytest.mark.benchmark
class TestMemoryPerformance:
    """内存性能测试"""

    @pytest.mark.asyncio
    async def test_memory_leak(self):
        """测试内存泄漏 - 1000次查询"""
        import psutil
        import os
        from olav.agents.orchestrator import create_orchestrator

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        orchestrator = create_orchestrator()

        # 执行1000次查询
        for i in range(1000):
            await orchestrator.ainvoke({
                "messages": [HumanMessage(content=f"查询设备{i % 10}")]
            })

            # 每100次检查一次
            if i % 100 == 0:
                current_memory = process.memory_info().rss / 1024 / 1024
                memory_growth = current_memory - initial_memory
                print(f"第{i}次查询，内存增长: {memory_growth:.2f}MB")

        final_memory = process.memory_info().rss / 1024 / 1024
        memory_growth = final_memory - initial_memory

        # 验收标准: 1000次查询后内存增长 <100MB
        assert memory_growth < 100, f"内存增长{memory_growth:.2f}MB，超过100MB阈值"


@pytest.mark.benchmark
class TestCachePerformance:
    """缓存性能测试 - 需要先实现缓存中间件"""

    @pytest.mark.asyncio
    async def test_cache_hit_performance(self):
        """测试缓存命中性能"""
        pytest.skip("需要先实现SmartCacheMiddleware")

        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        # 第一次查询 - 缓存miss
        start = time.time()
        await orchestrator.ainvoke({
            "messages": [HumanMessage(content="列出所有设备")]
        })
        first_duration = time.time() - start

        # 第二次相同查询 - 应该缓存hit
        start = time.time()
        await orchestrator.ainvoke({
            "messages": [HumanMessage(content="列出所有设备")]
        })
        second_duration = time.time() - start

        # 缓存命中应该显著更快 (<50ms)
        assert second_duration < 0.05, f"缓存命中耗时{second_duration*1000:.2f}ms"
        assert second_duration < first_duration / 5, "缓存命中应至少快5倍"


@pytest.mark.benchmark
class TestResourceUtilization:
    """资源利用率测试"""

    @pytest.mark.asyncio
    async def test_cpu_utilization(self):
        """测试CPU利用率"""
        import psutil
        from olav.agents.orchestrator import create_orchestrator

        orchestrator = create_orchestrator()

        # 测量CPU使用率
        cpu_before = psutil.cpu_percent(interval=1)

        # 执行100个查询
        for i in range(100):
            await orchestrator.ainvoke({
                "messages": [HumanMessage(content=f"查询{i}")]
            })

        cpu_after = psutil.cpu_percent(interval=1)
        cpu_increase = cpu_after - cpu_before

        # CPU增长应该在合理范围内 (<50%)
        assert cpu_increase < 50, f"CPU增长{cpu_increase:.1f}%，过高"

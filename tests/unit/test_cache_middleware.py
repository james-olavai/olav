"""
Cache Middleware Unit Tests (TDD - Phase 2.1)
测试智能缓存中间件
"""

import asyncio
import pytest
import time


class TestCacheMiddleware:
    """缓存中间件基础测试"""

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """测试缓存命中 - RED状态 (未实现)"""
        from olav.middleware.smart_cache import SmartCacheMiddleware

        middleware = SmartCacheMiddleware(ttl=300)

        # 第一次查询
        query1 = await middleware.process("show version R1")
        # 第二次相同查询应该命中缓存
        query2 = await middleware.process("show version R1")

        assert query1 == query2, "缓存命中应返回相同结果"
        assert middleware.cache_hit_rate > 0, "缓存命中率应>0"

    @pytest.mark.asyncio
    async def test_cache_miss(self):
        """测试缓存未命中"""
        from olav.middleware.smart_cache import SmartCacheMiddleware

        middleware = SmartCacheMiddleware(ttl=300)

        result1 = await middleware.process("query 1")
        result2 = await middleware.process("query 2")  # 不同查询

        assert middleware.cache_misses >= 2, "两次不同查询都应miss"

    @pytest.mark.asyncio
    async def test_cache_invalidation(self):
        """测试缓存失效 - TTL过期"""
        from olav.middleware.smart_cache import SmartCacheMiddleware

        middleware = SmartCacheMiddleware(ttl=1)  # 1秒TTL

        result1 = await middleware.process("show interfaces")
        await asyncio.sleep(2)  # 超过TTL
        result2 = await middleware.process("show interfaces")

        assert middleware.cache_misses == 2, "TTL过期后应重新查询"

    @pytest.mark.asyncio
    async def test_cache_memory_limit(self):
        """测试缓存内存限制"""
        from olav.middleware.smart_cache import SmartCacheMiddleware

        middleware = SmartCacheMiddleware(ttl=300, max_size=100)

        # 插入101个条目
        for i in range(101):
            await middleware.process(f"query {i}")

        # 缓存大小应该不超过max_size
        assert len(middleware.cache) <= 100, "缓存应遵守max_size限制"


class TestCachePerformance:
    """缓存性能测试"""

    @pytest.mark.asyncio
    async def test_cache_hit_latency(self):
        """测试缓存命中延迟 - 应<50ms"""
        from olav.middleware.smart_cache import SmartCacheMiddleware

        middleware = SmartCacheMiddleware(ttl=300)

        # 预热缓存
        await middleware.process("test query")

        # 测试缓存命中延迟
        start = time.time()
        await middleware.process("test query")
        duration = time.time() - start

        assert duration < 0.05, f"缓存命中延迟{duration*1000:.2f}ms，超过50ms"

    @pytest.mark.asyncio
    async def test_cache_memory_footprint(self):
        """测试缓存内存占用 - 1000条<100MB"""
        import sys
        from olav.middleware.smart_cache import SmartCacheMiddleware

        middleware = SmartCacheMiddleware(ttl=300)

        # 插入1000个条目
        for i in range(1000):
            await middleware.process(f"query {i}" * 100)  # 每个查询约100字节

        # 粗略估算内存占用
        cache_size_bytes = sys.getsizeof(middleware.cache)
        cache_size_mb = cache_size_bytes / (1024 * 1024)

        assert cache_size_mb < 100, f"1000条缓存占用{cache_size_mb:.2f}MB，超过100MB"


class TestCacheEdgeCases:
    """缓存边界情况测试"""

    @pytest.mark.asyncio
    async def test_empty_query(self):
        """测试空查询"""
        from olav.middleware.smart_cache import SmartCacheMiddleware

        middleware = SmartCacheMiddleware(ttl=300)

        result = await middleware.process("")
        assert result is not None, "空查询应返回有效结果（可能是错误）"

    @pytest.mark.asyncio
    async def test_very_long_query(self):
        """测试超长查询"""
        from olav.middleware.smart_cache import SmartCacheMiddleware

        middleware = SmartCacheMiddleware(ttl=300)

        long_query = "A" * 10000  # 10KB查询
        result = await middleware.process(long_query)
        assert result is not None

    @pytest.mark.asyncio
    async def test_concurrent_cache_access(self):
        """测试并发缓存访问"""
        from olav.middleware.smart_cache import SmartCacheMiddleware

        middleware = SmartCacheMiddleware(ttl=300)

        # 并发10个相同查询
        results = await asyncio.gather(*[
            middleware.process("concurrent query")
            for _ in range(10)
        ])

        # 所有结果应该一致
        assert len(set(str(r) for r in results)) == 1, "并发查询应返回一致结果"

        # 应该只有1次miss（第一次），其余9次hit
        assert middleware.cache_hits >= 9, "并发查询应命中缓存"

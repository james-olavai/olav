"""
Rate Limiter & Circuit Breaker Unit Tests (TDD - Phase 2.2)
测试限流和熔断器中间件
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, patch


class TestRateLimiter:
    """限流器测试"""

    @pytest.mark.asyncio
    async def test_rate_limiting(self):
        """测试限流功能 - RED状态 (未实现)"""
        from olav.middleware.resilience import RateLimiterMiddleware, RateLimitError

        limiter = RateLimiterMiddleware(max_requests=10, window=60)

        # 前10个请求应该成功
        for i in range(10):
            result = await limiter.process(f"query {i}")
            assert result is not None, f"第{i+1}个请求应该成功"

        # 第11个请求应该被限流
        with pytest.raises(RateLimitError, match="Rate limit exceeded"):
            await limiter.process("query 11")

    @pytest.mark.asyncio
    async def test_rate_limiter_window_sliding(self):
        """测试滑动窗口"""
        from olav.middleware.resilience import RateLimiterMiddleware

        limiter = RateLimiterMiddleware(max_requests=5, window=2)

        # 发送5个请求
        for i in range(5):
            await limiter.process(f"query {i}")

        # 等待2秒，窗口应该重置
        await asyncio.sleep(2.1)

        # 现在应该可以再发送5个
        for i in range(5):
            result = await limiter.process(f"query new {i}")
            assert result is not None

    @pytest.mark.asyncio
    async def test_rate_limiter_per_user(self):
        """测试按用户限流"""
        from olav.middleware.resilience import RateLimiterMiddleware

        limiter = RateLimiterMiddleware(max_requests=3, window=60)

        # 用户A发送3个请求
        for i in range(3):
            await limiter.process(f"query {i}", user_id="user_a")

        # 用户A应该被限流
        with pytest.raises(Exception):
            await limiter.process("query 4", user_id="user_a")

        # 用户B应该还能发送
        result = await limiter.process("query 1", user_id="user_b")
        assert result is not None


class TestCircuitBreaker:
    """熔断器测试"""

    @pytest.mark.asyncio
    async def test_circuit_breaker_open(self):
        """测试熔断器打开 - RED状态 (未实现)"""
        from olav.middleware.resilience import CircuitBreakerMiddleware, CircuitOpenError

        breaker = CircuitBreakerMiddleware(failure_threshold=3, timeout=5)

        # 模拟3次失败
        for i in range(3):
            with pytest.raises(Exception):
                await breaker.process("failing_query")

        # 熔断器应该打开
        assert breaker.state == "OPEN", "3次失败后熔断器应打开"

        # 后续请求直接拒绝
        with pytest.raises(CircuitOpenError):
            await breaker.process("normal_query")

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open(self):
        """测试熔断器半开状态"""
        from olav.middleware.resilience import CircuitBreakerMiddleware

        breaker = CircuitBreakerMiddleware(failure_threshold=2, timeout=1)

        # 触发熔断
        for i in range(2):
            with pytest.raises(Exception):
                await breaker.process("failing_query")

        assert breaker.state == "OPEN"

        # 等待timeout
        await asyncio.sleep(1.1)

        # 应该进入半开状态
        # 下一个成功请求应该关闭熔断器
        with patch.object(breaker, '_execute', new_callable=AsyncMock, return_value="success"):
            result = await breaker.process("recovery_query")
            assert result == "success"
            assert breaker.state == "CLOSED", "成功请求应关闭熔断器"

    @pytest.mark.asyncio
    async def test_circuit_breaker_auto_recovery(self):
        """测试熔断器自动恢复"""
        from olav.middleware.resilience import CircuitBreakerMiddleware

        breaker = CircuitBreakerMiddleware(failure_threshold=2, timeout=1)

        # 触发熔断
        for i in range(2):
            with pytest.raises(Exception):
                await breaker.process("failing_query")

        # 等待恢复
        await asyncio.sleep(1.5)

        # 应该可以尝试请求
        with patch.object(breaker, '_execute', new_callable=AsyncMock, return_value="success"):
            result = await breaker.process("query")
            assert result is not None


class TestRateLimiterCircuitBreakerIntegration:
    """限流器和熔断器集成测试"""

    @pytest.mark.asyncio
    async def test_combined_middleware(self):
        """测试组合使用限流器和熔断器"""
        from olav.middleware.resilience import (
            RateLimiterMiddleware,
            CircuitBreakerMiddleware,
            RateLimitError,
        )

        limiter = RateLimiterMiddleware(max_requests=5, window=60)
        breaker = CircuitBreakerMiddleware(failure_threshold=3, timeout=5)

        async def process_with_both(query: str):
            # 先经过限流器
            await limiter.process(query)
            # 再经过熔断器
            return await breaker.process(query)

        # 发送5个正常请求
        for i in range(5):
            with patch.object(breaker, '_execute', new_callable=AsyncMock, return_value="ok"):
                result = await process_with_both(f"query {i}")
                assert result == "ok"

        # 第6个请求应该被限流
        with pytest.raises(RateLimitError):
            await process_with_both("query 6")

    @pytest.mark.asyncio
    async def test_metrics_collection(self):
        """测试限流器和熔断器指标收集"""
        from olav.middleware.resilience import RateLimiterMiddleware, CircuitBreakerMiddleware

        limiter = RateLimiterMiddleware(max_requests=10, window=60)
        breaker = CircuitBreakerMiddleware(failure_threshold=3, timeout=5)

        # 发送一些请求
        for i in range(5):
            with patch.object(breaker, '_execute', new_callable=AsyncMock, return_value="ok"):
                await limiter.process(f"query {i}")
                await breaker.process(f"query {i}")

        # 检查指标
        limiter_metrics = limiter.get_metrics()
        assert limiter_metrics["total_requests"] == 5
        assert limiter_metrics["rejected_requests"] == 0

        breaker_metrics = breaker.get_metrics()
        assert breaker_metrics["total_requests"] == 5
        assert breaker_metrics["failures"] == 0
        assert breaker_metrics["state"] == "CLOSED"

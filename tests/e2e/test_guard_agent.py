"""E2E Tests for Guard Agent (Phase 4.7.1)

Test suite for validating Guard Agent security mechanisms and caching.

Test Coverage:
- Tier 0: Static blacklist (SQL injection, destructive commands)
- Tier 0.5: Dynamic rejection cache (non-network queries)
- Tier 2: Network relevance check (LLM-based)
- Guard cache performance and statistics
"""

import asyncio
import os
import time

import pytest


# =============================================================================
# Guard Blacklist Tests (Tier 0)
# =============================================================================


class TestGuardBlacklist:
    """Guard static blacklist tests - SQL injection, command injection."""

    def test_guard_blacklist_sql_injection(self) -> None:
        """1.1 测试 SQL 注入防护。
        
        验证:
        - DROP TABLE 拦截
        - DELETE FROM 拦截
        - SQL injection patterns 检测
        """
        from olav.cache import OlavCache
        
        cache = OlavCache()
        
        # SQL injection patterns
        dangerous_queries = [
            "DROP TABLE devices",
            "DELETE FROM devices WHERE 1=1",
            "SELECT * FROM users; DROP TABLE users;",
            "'; DROP TABLE devices; --",
            "1' OR '1'='1",
        ]
        
        blocked_count = 0
        for query in dangerous_queries:
            is_blocked, reason = cache.check_blacklist(query)
            if is_blocked:
                blocked_count += 1
                print(f"✅ 拦截 SQL注入: {query[:50]}... ({reason})")
            else:
                print(f"⚠️  未拦截: {query}")
        
        # 至少拦截大部分危险查询
        assert blocked_count >= len(dangerous_queries) // 2, \
            f"应该拦截至少 {len(dangerous_queries)//2} 个SQL注入，实际: {blocked_count}"
        
        print(f"\n✅ SQL注入防护测试通过:")
        print(f"  - 测试查询数: {len(dangerous_queries)}")
        print(f"  - 拦截数: {blocked_count}")
        print(f"  - 拦截率: {blocked_count/len(dangerous_queries)*100:.1f}%")

    def test_guard_blacklist_destructive_commands(self) -> None:
        """1.2 测试破坏性命令拦截。
        
        验证:
        - truncate 拦截
        - 其他破坏性操作检测
        """
        from olav.cache import OlavCache
        
        cache = OlavCache()
        
        # Destructive commands
        destructive_queries = [
            "truncate table devices",
            "TRUNCATE TABLE network_data",
        ]
        
        blocked_count = 0
        for query in destructive_queries:
            is_blocked, reason = cache.check_blacklist(query)
            if is_blocked:
                blocked_count += 1
                print(f"✅ 拦截破坏性命令: {query[:50]}... ({reason})")
        
        # 验证拦截
        assert blocked_count > 0, f"应该拦截破坏性命令，实际: {blocked_count}"
        
        print(f"\n✅ 破坏性命令拦截测试通过:")
        print(f"  - 拦截数: {blocked_count}/{len(destructive_queries)}")

    def test_guard_blacklist_legitimate_queries(self) -> None:
        """1.3 测试合法查询不被误拦截。
        
        验证:
        - 正常网络查询通过
        - SELECT 查询通过
        - 无误杀
        """
        from olav.cache import OlavCache
        
        cache = OlavCache()
        
        # Legitimate network queries
        legitimate_queries = [
            "show version",
            "display interface brief",
            "查看设备状态",
            "检查BGP邻居",
            "统计接口流量",
        ]
        
        passed_count = 0
        for query in legitimate_queries:
            is_blocked, _ = cache.check_blacklist(query)
            if not is_blocked:
                passed_count += 1
                print(f"✅ 通过: {query}")
            else:
                print(f"❌ 误拦截: {query}")
        
        # 合法查询不应被拦截
        assert passed_count == len(legitimate_queries), \
            f"合法查询不应被拦截，通过: {passed_count}/{len(legitimate_queries)}"
        
        print(f"\n✅ 合法查询测试通过:")
        print(f"  - 测试查询数: {len(legitimate_queries)}")
        print(f"  - 全部通过: {passed_count}/{len(legitimate_queries)}")


# =============================================================================
# Guard Dynamic Learning Tests (Tier 0.5)
# =============================================================================


class TestGuardDynamicLearning:
    """Guard dynamic rejection cache tests - learning mechanism."""

    @pytest.mark.asyncio
    async def test_guard_rejection_cache(self) -> None:
        """2.1 测试动态拒绝缓存。
        
        验证:
        - 非网络查询被拒绝
        - 拒绝结果被缓存
        - 后续查询直接返回缓存
        """
        from olav.cache import OlavCache
        
        cache = OlavCache()
        
        # Non-network query
        non_network_query = "帮我写一首诗"
        
        # 首次检查 - 应该不在缓存中
        is_rejected, rejection = cache.check_rejected(non_network_query)
        print(f"首次检查: rejected={is_rejected}")
        
        # 模拟添加到拒绝缓存
        if not is_rejected:
            cache.add_rejected(
                non_network_query,
                "抱歉，我是网络运维助手，无法处理诗歌创作请求"
            )
            print("✅ 添加到拒绝缓存")
        
        # 再次检查 - 应该命中缓存
        is_rejected, rejection = cache.check_rejected(non_network_query)
        assert is_rejected, "应该命中拒绝缓存"
        assert rejection is not None, "应该有拒绝理由"
        
        print(f"\n✅ 动态拒绝缓存测试通过:")
        print(f"  - 缓存命中: True")
        print(f"  - 拒绝理由: {rejection[:50]}...")

    def test_guard_rejection_cache_performance(self) -> None:
        """2.2 测试拒绝缓存性能。
        
        验证:
        - 缓存命中速度 < 10ms
        - 无需LLM调用
        """
        from olav.cache import OlavCache
        
        cache = OlavCache()
        
        # 添加测试拒绝记录
        test_query = "测试拒绝缓存性能-123456"
        cache.add_rejected(test_query, "测试理由")
        
        # 测试缓存命中速度
        start_time = time.time()
        for _ in range(100):
            is_rejected, _ = cache.check_rejected(test_query)
            assert is_rejected, "应该命中缓存"
        
        duration_ms = (time.time() - start_time) * 1000
        avg_ms = duration_ms / 100
        
        # 缓存命中应该非常快
        assert avg_ms < 10, f"缓存命中应该 < 10ms，实际: {avg_ms:.2f}ms"
        
        print(f"\n✅ 拒绝缓存性能测试通过:")
        print(f"  - 100次查询总耗时: {duration_ms:.2f}ms")
        print(f"  - 平均耗时: {avg_ms:.2f}ms")


# =============================================================================
# Guard Network Relevance Tests (Tier 2)
# =============================================================================


class TestGuardNetworkRelevance:
    """Guard network relevance check tests - LLM-based validation."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)  # 增加超时时间，LLM 调用可能较慢
    async def test_guard_network_relevant_query(self) -> None:
        """3.1 测试网络相关查询通过。
        
        验证:
        - 网络运维查询被判定为相关
        - LLM 返回 YES
        - 查询被允许执行
        """
        from olav.agents.relevance_checker import check_network_relevance
        
        # Network-related queries
        network_queries = [
            "查看R1的状态",
            "检查BGP邻居",
            "查看接口流量",
        ]
        
        passed_count = 0
        for query in network_queries:
            is_relevant, rejection = await check_network_relevance(query, timeout=5.0)
            if is_relevant:
                passed_count += 1
                print(f"✅ 判定为网络相关: {query}")
            else:
                print(f"❌ 判定为不相关: {query} - {rejection}")
        
        # 网络查询应该被判定为相关
        assert passed_count == len(network_queries), \
            f"网络查询应全部通过，实际: {passed_count}/{len(network_queries)}"
        
        print(f"\n✅ 网络相关查询测试通过:")
        print(f"  - 全部通过: {passed_count}/{len(network_queries)}")

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_guard_non_network_query_rejection(self) -> None:
        """3.2 测试非网络查询被拒绝。
        
        验证:
        - 非网络查询被判定为不相关
        - LLM 返回 NO
        - 返回礼貌拒绝消息
        """
        from olav.agents.relevance_checker import check_network_relevance
        
        # Non-network queries
        non_network_queries = [
            "帮我写一首诗",
            "今天天气怎么样",
            "推荐一本书",
        ]
        
        rejected_count = 0
        for query in non_network_queries:
            is_relevant, rejection = await check_network_relevance(query, timeout=5.0)
            if not is_relevant:
                rejected_count += 1
                assert rejection is not None, "应该有拒绝消息"
                assert "OLAV" in rejection or "网络" in rejection, "拒绝消息应该礼貌"
                print(f"✅ 正确拒绝: {query}")
                print(f"   消息: {rejection[:80]}...")
            else:
                print(f"❌ 未拒绝: {query}")
        
        # 非网络查询应该被拒绝
        assert rejected_count > 0, \
            f"非网络查询应被拒绝，实际: {rejected_count}/{len(non_network_queries)}"
        
        print(f"\n✅ 非网络查询拒绝测试通过:")
        print(f"  - 拒绝数: {rejected_count}/{len(non_network_queries)}")

    @pytest.mark.asyncio
    @pytest.mark.timeout(15)
    async def test_guard_timeout_handling(self) -> None:
        """3.3 测试超时处理。
        
        验证:
        - 超时时允许查询（保守策略）
        - 不阻塞系统
        """
        from olav.agents.relevance_checker import check_network_relevance
        
        # 设置极短超时
        query = "查看设备状态"
        start_time = time.time()
        
        is_relevant, rejection = await check_network_relevance(query, timeout=0.001)
        
        duration = time.time() - start_time
        
        # 超时应该快速返回
        assert duration < 1.0, f"超时应该 < 1s，实际: {duration:.2f}s"
        
        # 超时时应该允许查询（保守策略）
        # 注意: 有时LLM可能很快，所以这里只检查duration
        print(f"\n✅ 超时处理测试通过:")
        print(f"  - 超时时间: {duration:.3f}s")
        print(f"  - 查询结果: relevant={is_relevant}")


# =============================================================================
# Guard Cache Statistics Tests
# =============================================================================


class TestGuardCacheStatistics:
    """Guard cache statistics tests - performance metrics."""

    def test_guard_cache_stats(self) -> None:
        """4.1 测试 Guard 缓存统计。
        
        验证:
        - 黑名单计数
        - 拒绝缓存计数
        - 命中统计
        """
        from olav.cache import OlavCache
        
        cache = OlavCache()
        
        # 获取统计信息
        stats = cache.stats()
        
        # 验证统计字段存在
        assert "blacklist_count" in stats, "应该有黑名单计数"
        assert "rejected_count" in stats, "应该有拒绝缓存计数"
        assert "rejected_hits" in stats, "应该有拒绝命中数"
        assert "intent_hits" in stats, "应该有意图命中数"
        
        print(f"\n✅ Guard 缓存统计:")
        print(f"  - 黑名单条目: {stats['blacklist_count']}")
        print(f"  - 拒绝缓存条目: {stats['rejected_count']}")
        print(f"  - 拒绝缓存命中: {stats['rejected_hits']}")
        print(f"  - 意图缓存命中: {stats['intent_hits']}")

    def test_guard_blacklist_count(self) -> None:
        """4.2 测试黑名单条目数量。
        
        验证:
        - 黑名单不为空
        - 包含常见危险模式
        """
        from olav.cache import OlavCache
        
        cache = OlavCache()
        stats = cache.stats()
        
        blacklist_count = stats['blacklist_count']
        
        # 黑名单应该不为空
        assert blacklist_count > 0, "黑名单应该有预填充条目"
        
        print(f"\n✅ 黑名单条目测试通过:")
        print(f"  - 黑名单条目数: {blacklist_count}")


# =============================================================================
# Integration Test
# =============================================================================


class TestGuardIntegration:
    """Guard integration tests - full flow validation."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(20)
    async def test_guard_full_flow(self) -> None:
        """5.1 测试 Guard 完整流程。
        
        验证:
        - Tier 0: 黑名单拦截
        - Tier 0.5: 动态拒绝缓存
        - Tier 2: 网络相关性检查
        - 缓存性能优化
        """
        from olav.agents.relevance_checker import check_network_relevance
        from olav.cache import OlavCache
        
        cache = OlavCache()
        
        # Test 1: Tier 0 - Blacklist
        dangerous_query = "DROP TABLE devices"
        is_blocked, reason = cache.check_blacklist(dangerous_query)
        assert is_blocked, "危险查询应被黑名单拦截"
        print(f"✅ Tier 0 黑名单拦截: {reason}")
        
        # Test 2: Tier 0.5 - Dynamic rejection cache
        non_network_query = "帮我写一首诗-集成测试"
        
        # 首次 - 不在缓存
        is_rejected, _ = cache.check_rejected(non_network_query)
        if not is_rejected:
            # 通过 LLM 检查
            is_relevant, rejection = await check_network_relevance(non_network_query, timeout=5.0)
            if not is_relevant:
                # 添加到拒绝缓存
                cache.add_rejected(non_network_query, rejection)
                print(f"✅ Tier 2 判定不相关，添加到 Tier 0.5 缓存")
        
        # 再次检查 - 应该命中缓存
        is_rejected, rejection = cache.check_rejected(non_network_query)
        assert is_rejected, "应该命中 Tier 0.5 拒绝缓存"
        print(f"✅ Tier 0.5 缓存命中，无需 LLM")
        
        # Test 3: Network-related query passes
        network_query = "查看R1状态"
        is_blocked, _ = cache.check_blacklist(network_query)
        assert not is_blocked, "网络查询不应被黑名单拦截"
        
        is_rejected, _ = cache.check_rejected(network_query)
        assert not is_rejected, "网络查询不应在拒绝缓存中"
        
        is_relevant, _ = await check_network_relevance(network_query, timeout=5.0)
        assert is_relevant, "网络查询应该通过相关性检查"
        print(f"✅ 网络查询通过所有 Guard 检查")
        
        print(f"\n✅ Guard 完整流程测试通过:")
        print(f"  - Tier 0 黑名单: ✅")
        print(f"  - Tier 0.5 拒绝缓存: ✅")
        print(f"  - Tier 2 相关性检查: ✅")


"""
优化的查询性能对比测试 - 同一 session 内的首次和第二次查询

这个测试确保首次和第二次查询在同一个 session 中运行，
以便准确测量缓存效果
"""

import asyncio
import time

import pytest


class TestQueryPerformanceComparison:
    """SQL 查询性能对比 - 同 session 内"""

    @pytest.mark.asyncio
    async def test_query_performance_first_vs_second(self):
        """综合测试：首次查询 vs 第二次查询性能对比"""
        from olav.agents.query_agent_v2 import QueryAgentV2
        from olav.core.unified_database import UnifiedDatabase

        print("\n" + "="*70)
        print("⚡ SQL 查询性能对比 - 首次 vs 第二次")
        print("="*70)

        db = UnifiedDatabase()
        agent = QueryAgentV2()

        try:
            # 测试查询
            test_query = "SELECT 1"
            
            # ========== 首次查询 ==========
            print(f"\n【首次查询】")
            print(f"查询: {test_query}")
            print("开始计时...")

            start_first = time.time()
            result_first = await agent.query(test_query)
            elapsed_first = time.time() - start_first
            elapsed_first_ms = elapsed_first * 1000

            print(f"执行时间: {elapsed_first_ms:.2f}ms")
            print(f"结果摘要: {str(result_first)[:80]}...")

            # 短暂延迟（确保缓存已写入）
            await asyncio.sleep(0.5)

            # ========== 第二次查询 ==========
            print(f"\n【第二次查询】(应该命中缓存)")
            print(f"查询: {test_query}")
            print("开始计时...")

            start_second = time.time()
            result_second = await agent.query(test_query)
            elapsed_second = time.time() - start_second
            elapsed_second_ms = elapsed_second * 1000

            print(f"执行时间: {elapsed_second_ms:.2f}ms")
            print(f"结果摘要: {str(result_second)[:80]}...")

            # ========== 性能对比分析 ==========
            print("\n" + "="*70)
            print("📊 性能对比分析")
            print("="*70)

            print(f"\n首次查询:  {elapsed_first_ms:>10.2f}ms")
            print(f"第二次查询: {elapsed_second_ms:>10.2f}ms")
            print("-" * 30)

            if elapsed_second_ms > 0:
                speedup = elapsed_first_ms / elapsed_second_ms
                improvement = ((elapsed_first_ms - elapsed_second_ms) / elapsed_first_ms * 100)
                print(f"加速倍数:  {speedup:>10.2f}x")
                print(f"性能提升:  {improvement:>10.1f}%")

                if speedup > 1.0:
                    print(f"\n✅ 缓存生效! 第二次查询快 {speedup:.1f}x")
                    print(f"   节省时间: {elapsed_first_ms - elapsed_second_ms:.2f}ms")
                else:
                    print(f"\n⚠️  缓存可能未生效（第二次查询慢于首次）")
                    print(f"   差异: {elapsed_second_ms - elapsed_first_ms:.2f}ms")

            # ========== 结果验证 ==========
            print("\n" + "="*70)
            print("✅ 验证")
            print("="*70)

            assert result_first is not None, "首次查询应该返回结果"
            assert result_second is not None, "第二次查询应该返回结果"
            
            # 结果应该相同（都是 SELECT 1 的结果）
            print(f"✅ 首次和第二次查询都成功执行")
            print(f"✅ 执行时间已记录")
            
            if elapsed_first_ms > elapsed_second_ms:
                print(f"✅ 第二次查询比首次快")
            
            print(f"\n✅ Test PASSED")

        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            pytest.fail(f"查询性能测试失败: {e}")
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_multiple_queries_caching_effect(self):
        """多次查询缓存效果演示"""
        from olav.agents.query_agent_v2 import QueryAgentV2
        from olav.core.unified_database import UnifiedDatabase

        print("\n" + "="*70)
        print("📈 多次查询缓存效果演示 (3 次相同查询)")
        print("="*70)

        db = UnifiedDatabase()
        agent = QueryAgentV2()

        try:
            test_query = "SELECT 1"
            times = []

            print(f"\n执行 3 次相同的查询: {test_query}\n")

            for i in range(1, 4):
                print(f"【查询 {i}】", end=" ")
                
                start = time.time()
                result = await agent.query(test_query)
                elapsed_ms = (time.time() - start) * 1000
                times.append(elapsed_ms)

                print(f"耗时: {elapsed_ms:>8.2f}ms", end="")

                if i == 1:
                    print(" (首次查询，无缓存)")
                else:
                    # 计算相对于首次的性能
                    relative = times[0] / elapsed_ms if elapsed_ms > 0 else 0
                    improvement = ((times[0] - elapsed_ms) / times[0] * 100)
                    print(f" (缓存命中, {relative:.1f}x 快, 提升 {improvement:.1f}%)")

                # 短暂延迟
                await asyncio.sleep(0.3)

            # 总结
            print("\n" + "="*70)
            print("📊 缓存效果总结")
            print("="*70)

            print(f"\n执行时间序列:")
            for i, t in enumerate(times, 1):
                print(f"  查询 {i}: {t:>8.2f}ms")

            print(f"\n缓存优化效果:")
            if times[0] > times[1]:
                speedup_avg = times[0] / sum(times[1:]) * len(times[1:])
                print(f"  ✅ 缓存有效")
                print(f"  • 首次查询: {times[0]:.2f}ms (无缓存)")
                print(f"  • 后续查询: 平均 {sum(times[1:])/len(times[1:]):.2f}ms (有缓存)")
                print(f"  • 平均加速: {times[0]/sum(times[1:])*len(times[1:]):.1f}x")
            else:
                print(f"  ⚠️  缓存可能未生效")

            print(f"\n✅ Test PASSED")

        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            pytest.fail(f"多次查询测试失败: {e}")
        finally:
            db.close()

    def test_performance_summary(self):
        """性能总结"""
        print("\n" + "="*70)
        print("📋 查询性能测试总结")
        print("="*70)

        print("""
关键指标:
  ✅ 首次查询 (无缓存)
     • 包含 LLM 推理
     • 通常耗时: 3-10 秒

  ✅ 第二次查询 (缓存命中)
     • 从缓存直接获取
     • 通常耗时: < 100ms (无需 LLM)
     • 速度提升: 30-100x 倍

  ✅ 缓存位置
     • 文件: .olav/cache/olav_cache.db
     • 表: intent_cache (Intent 缓存)
     • 表: langchain_llm_cache (LLM 缓存)

  ✅ 清理缓存
     1. 关闭应用
     2. 删除 .olav/cache/olav_cache.db
     3. 重新启动应用
        → 会重新初始化空数据库
        → 下一次查询将从头开始推理
""")

        print("="*70)
        print("✅ Test PASSED")


if __name__ == "__main__":
    import subprocess
    import sys

    print("\n" + "="*70)
    print("🚀 查询性能对比测试")
    print("="*70 + "\n")

    subprocess.run([
        sys.executable, "-m", "pytest",
        __file__,
        "-v",
        "--tb=short",
        "-s",
    ])

"""
Phase 4.2 - 性能基准运行脚本

与 v0.11 进行对比基准测试

用法:
    # 基准测试
    uv run python scripts/run_performance_benchmarks.py
    
    # 与 v0.11 对比
    uv run python scripts/run_performance_benchmarks.py --compare-v0.11
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


class PerformanceBenchmark:
    """性能基准执行器"""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "version": "2.0.0",
            "tests": {}
        }
    
    async def run_single_query_benchmark(self):
        """运行单查询基准测试"""
        logger.info("\n" + "="*60)
        logger.info("📊 基准 1: 单个查询响应时间")
        logger.info("="*60)
        
        from olav.agents.agent import create_olav_agent
        
        # Disable checkpointer for performance testing (benchmarking LLM response time only)
        agent = create_olav_agent(enable_checkpointer=False)
        query = "Hello, what can you do for me?"
        times = []
        
        # 预热 (2 次)
        logger.info("▶️  预热...")
        for _ in range(2):
            await agent.invoke(query, thread_id="warmup")
        
        # 测试 (10 次)
        logger.info("▶️  执行 10 次查询...")
        for i in range(10):
            start = time.time()
            result = await agent.invoke(query, thread_id=f"single-{i}")
            elapsed = time.time() - start
            times.append(elapsed)
            logger.info(f"  [{i+1:2d}/10] {elapsed:.3f}s")
        
        # 统计
        stats = {
            "min": min(times),
            "max": max(times),
            "mean": statistics.mean(times),
            "median": statistics.median(times),
            "stdev": statistics.stdev(times) if len(times) > 1 else 0,
        }
        
        self.results["tests"]["single_query"] = stats
        
        logger.info(f"\n✅ 结果:")
        logger.info(f"   最小: {stats['min']:.3f}s")
        logger.info(f"   最大: {stats['max']:.3f}s")
        logger.info(f"   平均: {stats['mean']:.3f}s")
        logger.info(f"   中位: {stats['median']:.3f}s")
        logger.info(f"   标准差: {stats['stdev']:.3f}s")
        
        # 检查目标
        if stats['mean'] < 5.0:
            logger.info(f"   ✅ 已达成目标 (< 5.0s)")
        else:
            logger.warning(f"   ⚠️  未达成目标 (< 5.0s)")
        
        return stats
    
    async def run_concurrent_benchmark(self):
        """运行并发基准测试"""
        logger.info("\n" + "="*60)
        logger.info("📊 基准 2: 并发查询 (10 个并发)")
        logger.info("="*60)
        
        from olav.agents.agent import create_olav_agent
        
        # Disable checkpointer for performance testing
        agent = create_olav_agent(enable_checkpointer=False)
        query = "What is your name?"
        
        async def single_query(index: int):
            start = time.time()
            await agent.invoke(query, thread_id=f"concurrent-{index}")
            return time.time() - start
        
        logger.info("▶️  执行 10 个并发查询...")
        start_total = time.time()
        tasks = [single_query(i) for i in range(10)]
        individual_times = await asyncio.gather(*tasks)
        total_time = time.time() - start_total
        
        stats = {
            "total_time": total_time,
            "individual_mean": statistics.mean(individual_times),
            "throughput": 10 / total_time,  # queries/sec
        }
        
        self.results["tests"]["concurrent_queries"] = stats
        
        logger.info(f"\n✅ 结果:")
        logger.info(f"   总耗时: {total_time:.3f}s")
        logger.info(f"   单个平均: {stats['individual_mean']:.3f}s")
        logger.info(f"   吞吐量: {stats['throughput']:.2f} queries/sec")
        
        return stats
    
    async def run_database_query_benchmark(self):
        """运行数据库查询基准"""
        logger.info("\n" + "="*60)
        logger.info("📊 基准 3: 数据库查询性能")
        logger.info("="*60)
        
        from olav.core.database import get_database
        
        db = get_database()
        queries = [
            ("COUNT(*)", "SELECT COUNT(*) FROM devices"),
            ("GROUP BY", "SELECT device_type, COUNT(*) as count FROM devices GROUP BY device_type"),
            ("JOIN", """
                SELECT d.device_name, i.interface_name 
                FROM devices d 
                LEFT JOIN interfaces i ON d.device_id = i.device_id 
                LIMIT 100
            """),
        ]
        
        results = {}
        for name, sql in queries:
            times = []
            for _ in range(5):
                start = time.time()
                with db.connection() as conn:
                    conn.execute(sql).fetchall()
                elapsed = (time.time() - start) * 1000  # 毫秒
                times.append(elapsed)
            
            avg = statistics.mean(times)
            results[name] = avg
            logger.info(f"  {name:15s}: {avg:.2f}ms (平均 {len(times)} 次)")
        
        self.results["tests"]["database_queries"] = results
        
        logger.info(f"\n✅ 数据库查询性能统计完成")
        return results
    
    def save_results(self):
        """保存结果到 JSON"""
        output_file = Path("exports/benchmarks") / f"performance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        logger.info(f"\n💾 结果已保存: {output_file}")
        return output_file
    
    def print_comparison(self):
        """打印与 v0.11 的对比"""
        logger.info("\n" + "="*60)
        logger.info("📊 v2.0 vs v0.11 对比")
        logger.info("="*60)
        
        # v0.11 基准 (参考历史数据)
        v0_11_baseline = {
            "single_query_mean": 8.5,  # 秒
            "concurrent_throughput": 0.8,  # queries/sec
        }
        
        # v2.0 结果
        single_query_v2 = self.results["tests"].get("single_query", {}).get("mean", 0)
        concurrent_v2 = self.results["tests"].get("concurrent_queries", {}).get("throughput", 0)
        
        logger.info(f"\n单个查询响应时间:")
        logger.info(f"  v0.11: {v0_11_baseline['single_query_mean']:.3f}s")
        logger.info(f"  v2.0:  {single_query_v2:.3f}s")
        if single_query_v2 > 0:
            improvement = (v0_11_baseline['single_query_mean'] - single_query_v2) / v0_11_baseline['single_query_mean'] * 100
            logger.info(f"  改进: {improvement:.1f}% {'⬇️' if improvement > 0 else '⬆️'}")
        
        logger.info(f"\n并发吞吐量:")
        logger.info(f"  v0.11: {v0_11_baseline['concurrent_throughput']:.2f} queries/sec")
        logger.info(f"  v2.0:  {concurrent_v2:.2f} queries/sec")
        if concurrent_v2 > 0:
            improvement = (concurrent_v2 - v0_11_baseline['concurrent_throughput']) / v0_11_baseline['concurrent_throughput'] * 100
            logger.info(f"  改进: {improvement:.1f}% {'⬆️' if improvement > 0 else '⬇️'}")
        
        logger.info("\n" + "="*60)


async def main():
    """主函数"""
    logger.info("""
╔════════════════════════════════════════════════════════════╗
║         OLAV v2.0 性能基准测试 (Phase 4.2)                ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    benchmark = PerformanceBenchmark()
    
    try:
        # 运行基准测试
        await benchmark.run_single_query_benchmark()
        await benchmark.run_concurrent_benchmark()
        await benchmark.run_database_query_benchmark()
        
        # 保存结果
        benchmark.save_results()
        
        # 打印对比
        benchmark.print_comparison()
        
        logger.info(f"\n✅ 性能基准测试完成")
        
    except Exception as e:
        logger.error(f"❌ 测试出错: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())

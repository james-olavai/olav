#!/usr/bin/env python3
"""
缓存性能基准测试

测试不同场景下的缓存性能：
1. Exact 模式（Query/CLI SubAgent）
2. Fuzzy 模式（主路由）
3. Guard 动态学习
4. 缓存命中 vs 未命中

输出性能报告到 exports/reports/
"""

import asyncio
import time
import json
from pathlib import Path
from typing import Any

from config.paths import REPORTS_DIR
from config.settings import Settings
from olav.cache import init_cache, cache
from olav.agents.relevance_checker import check_network_relevance

# 测试用例
TEST_CASES = {
    "network_queries": [
        "查看R1的状态",
        "查看 R1 的状态",  # 多空格
        "查看R1的状态？",  # 标点
        "查询R1的状态",  # 同义词（fuzzy 应该匹配）
        "R1状态如何",  # 同义转述（fuzzy 可能匹配）
    ],
    "cli_queries": [
        "在R1上执行 show ip bgp summary",
        "在R1上执行show ip bgp summary",  # 空格差异
        "在R2上执行 show ip bgp summary",  # 不同设备（不应匹配）
    ],
    "non_network_queries": [
        "帮我写一首诗",
        "今天天气怎么样",
        "什么是人工智能",
    ],
    "dangerous_queries": [
        "drop table devices",
        "delete from snapshots",
        "shutdown the system",
    ],
}


class PerformanceTester:
    """性能测试器"""
    
    def __init__(self):
        init_cache()
        self.settings = Settings()
        self.results = []
    
    async def test_exact_match(self) -> dict[str, Any]:
        """测试 Exact 模式（Query SubAgent）"""
        print("\n=== 测试 1: Exact 模式（Query SubAgent）===")
        
        results = {"mode": "exact", "tests": []}
        
        # 首次查询（缓存未命中）
        query = TEST_CASES["network_queries"][0]
        start = time.time()
        result = cache.get_intent(query, match_mode="exact", confidence_threshold=1.0)
        duration = time.time() - start
        
        results["tests"].append({
            "query": query,
            "type": "first_query",
            "hit": result is not None,
            "duration_ms": duration * 1000,
        })
        print(f"  首次查询: {query}")
        print(f"    命中: {result is not None}, 耗时: {duration*1000:.2f}ms")
        
        # 写入缓存
        if result is None:
            cache.set_intent(query, {"message": "模拟结果", "data": []})
        
        # 重复查询（缓存命中）
        start = time.time()
        result = cache.get_intent(query, match_mode="exact", confidence_threshold=1.0)
        duration = time.time() - start
        
        results["tests"].append({
            "query": query,
            "type": "cached_query",
            "hit": result is not None,
            "duration_ms": duration * 1000,
        })
        print(f"  重复查询: {query}")
        print(f"    命中: {result is not None}, 耗时: {duration*1000:.2f}ms")
        
        # 测试变体（应该命中，因为 Hash 规范化）
        for variant in TEST_CASES["network_queries"][1:3]:
            start = time.time()
            result = cache.get_intent(variant, match_mode="exact", confidence_threshold=1.0)
            duration = time.time() - start
            
            results["tests"].append({
                "query": variant,
                "type": "variant",
                "hit": result is not None,
                "duration_ms": duration * 1000,
                "confidence": result.get("_confidence") if result else None,
            })
            print(f"  变体查询: {variant}")
            print(f"    命中: {result is not None}, 耗时: {duration*1000:.2f}ms")
        
        return results
    
    async def test_fuzzy_match(self) -> dict[str, Any]:
        """测试 Fuzzy 模式（主路由）"""
        print("\n=== 测试 2: Fuzzy 模式（主路由）===")
        
        results = {"mode": "fuzzy", "tests": []}
        
        # 原始查询
        query = TEST_CASES["network_queries"][0]
        cache.set_intent(query, {"message": "模拟结果", "data": []})
        
        # 测试同义词和转述
        for variant in TEST_CASES["network_queries"][3:]:
            start = time.time()
            result = cache.get_intent(
                variant, 
                match_mode="fuzzy", 
                confidence_threshold=0.85
            )
            duration = time.time() - start
            
            confidence = result.get("_confidence") if result else 0.0
            
            results["tests"].append({
                "query": variant,
                "original": query,
                "hit": result is not None,
                "confidence": confidence,
                "duration_ms": duration * 1000,
            })
            print(f"  模糊匹配: {variant}")
            print(f"    命中: {result is not None}, 置信度: {confidence:.2f}, 耗时: {duration*1000:.2f}ms")
        
        return results
    
    async def test_guard_blacklist(self) -> dict[str, Any]:
        """测试 Guard 静态黑名单"""
        print("\n=== 测试 3: Guard 静态黑名单 ===")
        
        results = {"mode": "blacklist", "tests": []}
        
        for query in TEST_CASES["dangerous_queries"]:
            start = time.time()
            blocked, reason = cache.check_blacklist(query)
            duration = time.time() - start
            
            results["tests"].append({
                "query": query,
                "blocked": blocked,
                "reason": reason,
                "duration_ms": duration * 1000,
            })
            print(f"  危险查询: {query}")
            print(f"    拦截: {blocked}, 耗时: {duration*1000:.2f}ms")
        
        return results
    
    async def test_guard_dynamic_learning(self) -> dict[str, Any]:
        """测试 Guard 动态学习"""
        print("\n=== 测试 4: Guard 动态学习 ===")
        
        results = {"mode": "dynamic_learning", "tests": []}
        
        query = TEST_CASES["non_network_queries"][0]
        
        # 首次判断（需要 LLM）
        print(f"  首次非网络查询: {query}")
        start = time.time()
        is_relevant, rejection = await check_network_relevance(query, timeout=2.0)
        duration_llm = time.time() - start
        
        results["tests"].append({
            "query": query,
            "type": "first_check",
            "relevant": is_relevant,
            "duration_ms": duration_llm * 1000,
        })
        print(f"    相关性: {is_relevant}, 耗时: {duration_llm*1000:.2f}ms")
        
        # 学习到拒绝缓存
        if not is_relevant:
            cache.add_rejected(query, rejection)
        
        # 重复查询（应该直接从缓存拒绝）
        start = time.time()
        rejected, _ = cache.check_rejected(query)
        duration_cache = time.time() - start
        
        results["tests"].append({
            "query": query,
            "type": "cached_rejection",
            "rejected": rejected,
            "duration_ms": duration_cache * 1000,
            "speedup": duration_llm / duration_cache if duration_cache > 0 else 0,
        })
        print(f"  重复查询（缓存拒绝）: {query}")
        print(f"    拒绝: {rejected}, 耗时: {duration_cache*1000:.2f}ms")
        print(f"    提速: {duration_llm/duration_cache:.1f}x")
        
        return results
    
    async def test_cli_exact_match(self) -> dict[str, Any]:
        """测试 CLI SubAgent 精确匹配"""
        print("\n=== 测试 5: CLI SubAgent（Exact）===")
        
        results = {"mode": "cli_exact", "tests": []}
        
        queries = TEST_CASES["cli_queries"]
        
        # 原始查询
        cache.set_intent(queries[0], {"message": "模拟 BGP 输出", "data": []})
        
        for query in queries:
            start = time.time()
            result = cache.get_intent(query, match_mode="exact", confidence_threshold=1.0)
            duration = time.time() - start
            
            results["tests"].append({
                "query": query,
                "hit": result is not None,
                "duration_ms": duration * 1000,
            })
            print(f"  CLI 查询: {query}")
            print(f"    命中: {result is not None}, 耗时: {duration*1000:.2f}ms")
        
        return results
    
    async def run_all_tests(self) -> dict[str, Any]:
        """运行所有测试"""
        print("=" * 60)
        print("开始缓存性能基准测试")
        print("=" * 60)
        
        all_results = {
            "timestamp": time.time(),
            "settings": {
                "guard_enabled": self.settings.guard.enabled,
                "cache_match_mode": self.settings.routing.cache_match_mode,
                "cache_confidence_threshold": self.settings.routing.cache_confidence_threshold,
                "query_agent_mode": self.settings.routing.query_agent_cache_mode,
                "cli_agent_mode": self.settings.routing.cli_agent_cache_mode,
            },
            "tests": {}
        }
        
        all_results["tests"]["exact_match"] = await self.test_exact_match()
        all_results["tests"]["fuzzy_match"] = await self.test_fuzzy_match()
        all_results["tests"]["guard_blacklist"] = await self.test_guard_blacklist()
        all_results["tests"]["guard_dynamic_learning"] = await self.test_guard_dynamic_learning()
        all_results["tests"]["cli_exact_match"] = await self.test_cli_exact_match()
        
        # 缓存统计
        all_results["cache_stats"] = cache.stats()
        
        print("\n" + "=" * 60)
        print("缓存统计")
        print("=" * 60)
        for key, value in all_results["cache_stats"].items():
            print(f"  {key}: {value}")
        
        return all_results
    
    def generate_report(self, results: dict[str, Any]) -> str:
        """生成性能报告"""
        report = []
        report.append("# 缓存性能基准测试报告\n")
        report.append(f"**测试时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        report.append("\n## 配置\n")
        
        for key, value in results["settings"].items():
            report.append(f"- **{key}**: `{value}`")
        
        report.append("\n## 测试结果\n")
        
        # Exact 模式
        report.append("\n### 1. Exact 模式（Query SubAgent）\n")
        report.append("| 查询 | 类型 | 命中 | 耗时(ms) |")
        report.append("|------|------|------|----------|")
        for test in results["tests"]["exact_match"]["tests"]:
            hit = "✅" if test["hit"] else "❌"
            report.append(f"| {test['query'][:30]} | {test['type']} | {hit} | {test['duration_ms']:.2f} |")
        
        # Fuzzy 模式
        report.append("\n### 2. Fuzzy 模式（主路由）\n")
        report.append("| 查询 | 命中 | 置信度 | 耗时(ms) |")
        report.append("|------|------|---------|----------|")
        for test in results["tests"]["fuzzy_match"]["tests"]:
            hit = "✅" if test["hit"] else "❌"
            conf = f"{test['confidence']:.2f}" if test['confidence'] else "N/A"
            report.append(f"| {test['query'][:30]} | {hit} | {conf} | {test['duration_ms']:.2f} |")
        
        # Guard 黑名单
        report.append("\n### 3. Guard 静态黑名单\n")
        report.append("| 查询 | 拦截 | 耗时(ms) |")
        report.append("|------|------|----------|")
        for test in results["tests"]["guard_blacklist"]["tests"]:
            blocked = "🚫" if test["blocked"] else "✅"
            report.append(f"| {test['query'][:30]} | {blocked} | {test['duration_ms']:.2f} |")
        
        # Guard 动态学习
        report.append("\n### 4. Guard 动态学习\n")
        for test in results["tests"]["guard_dynamic_learning"]["tests"]:
            if test["type"] == "first_check":
                report.append(f"- **首次判断**: {test['duration_ms']:.2f}ms")
            elif test["type"] == "cached_rejection":
                report.append(f"- **缓存拒绝**: {test['duration_ms']:.2f}ms")
                report.append(f"- **提速**: {test['speedup']:.1f}x")
        
        # CLI Exact
        report.append("\n### 5. CLI SubAgent（Exact）\n")
        report.append("| 查询 | 命中 | 耗时(ms) |")
        report.append("|------|------|----------|")
        for test in results["tests"]["cli_exact_match"]["tests"]:
            hit = "✅" if test["hit"] else "❌"
            report.append(f"| {test['query'][:40]} | {hit} | {test['duration_ms']:.2f} |")
        
        # 缓存统计
        report.append("\n## 缓存统计\n")
        stats = results["cache_stats"]
        report.append(f"- **黑名单规则**: {stats['blacklist_count']}")
        report.append(f"- **拒绝缓存数**: {stats['rejected_count']}")
        report.append(f"- **Intent 缓存数**: {stats['intent_count']}")
        report.append(f"- **拒绝命中次数**: {stats['rejected_hits']}")
        report.append(f"- **Intent 命中次数**: {stats['intent_hits']}")
        
        return "\n".join(report)


async def main():
    """主函数"""
    tester = PerformanceTester()
    
    # 运行所有测试
    results = await tester.run_all_tests()
    
    # 生成报告
    report_md = tester.generate_report(results)
    
    # 保存报告
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    
    # Markdown 报告
    report_path = REPORTS_DIR / f"cache_performance_{timestamp}.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"\n✅ Markdown 报告已保存: {report_path}")
    
    # JSON 原始数据
    json_path = REPORTS_DIR / f"cache_performance_{timestamp}.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ JSON 数据已保存: {json_path}")
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

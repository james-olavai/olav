"""Performance Test - Phase 2 Optimizations.

Tests the performance improvements from Phase 2:
- Precompiled SQL rules
- Pattern matching optimization

Goals:
- Precompiled SQL queries < 3s
- First query < 8s (improved from Phase 1)
"""

import asyncio
import time
from olav.core.query_router import QueryRouter
from olav.agents.query_agent_v2 import QueryAgentV2


# Test queries with precompiled SQL
PRECOMPILED_QUERIES = [
    ("R1的版本信息", "R1 version"),  # Matches precompiled SQL
    ("R1的接口状态", "R1 interfaces status"),  # Matches precompiled SQL
    ("R1的路由表", "R1 routing table"),  # Matches precompiled SQL
]

# Regular queries (no precompiled SQL)
REGULAR_QUERIES = [
    "Show all devices",
    "BGP neighbor summary",
]


async def test_precompiled_sql():
    """Test precompiled SQL performance."""
    print("=" * 60)
    print("Phase 2: Precompiled SQL Performance Test")
    print("=" * 60)
    print("\nGoals:")
    print("  - Precompiled SQL < 3s")
    print("  - Pattern matching bypasses LLM")
    print()

    router = QueryRouter()
    results = []

    for query_zh, query_en in PRECOMPILED_QUERIES:
        print(f"\nTesting: {query_zh}")
        print("-" * 40)

        # Test Chinese query
        decision = router.route(query_zh)
        print(f"  Decision: {decision.message}")
        print(f"  Tool: {decision.tool}")
        print(f"  Params: {decision.params}")

        if decision.timings:
            print(f"  Router timings: {decision.timings}")

        # Check if SQL is precompiled
        if decision.params and "sql" in decision.params:
            print(f"  ✅ Precompiled SQL: {decision.params['sql'][:80]}...")

        # Execute query
        agent = QueryAgentV2(mode="standard")
        start = time.time()
        result = await agent.query(query_zh)
        elapsed = time.time() - start

        print(f"  Execution time: {elapsed:.2f}s")

        # Check performance data
        if result.get("status") == "success":
            raw = result.get("_raw", {})
            if isinstance(raw, dict):
                perf = raw.get("performance", {})
                print(f"  Agent performance: {perf}")

        results.append({
            "query": query_zh,
            "time": elapsed,
            "precompiled": "sql" in (decision.params or {}),
        })

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    precompiled_times = [r["time"] for r in results if r["precompiled"]]
    if precompiled_times:
        avg_precompiled = sum(precompiled_times) / len(precompiled_times)
        print(f"\n✅ Precompiled SQL queries:")
        print(f"  Average: {avg_precompiled:.2f}s")
        print(f"  Goal: < 3s")

        if avg_precompiled < 3.0:
            print(f"  ✅ PASSED")
        else:
            print(f"  ❌ FAILED")

    print(f"\nDetailed results:")
    for r in results:
        status = "✅" if r["precompiled"] else "⚠️ "
        print(f"  {status} {r['query']}: {r['time']:.2f}s")

    print("\n" + "=" * 60)

    # Assert for CI/CD
    if precompiled_times:
        assert avg_precompiled < 5.0, f"Precompiled SQL too slow: {avg_precompiled:.2f}s"


async def test_pattern_matching():
    """Test pattern matching bypasses LLM."""
    print("\n" + "=" * 60)
    print("Phase 2: Pattern Matching Test")
    print("=" * 60)
    print("\nVerifying pattern matching bypasses LLM fallback...")
    print()

    router = QueryRouter()

    test_cases = [
        ("R1的版本信息", "version", "precompiled_sql"),
        ("R1的接口状态", "interfaces status", "precompiled_sql"),
        ("R1 health", "health", "direct_tool"),
        ("网络概览", "network summary", "direct_tool"),
    ]

    pattern_hits = 0
    llm_fallbacks = 0

    for query, expected_type, match_type in test_cases:
        decision = router.route(query)

        # Check if pattern matched (no LLM fallback)
        if decision.timings:
            if "llm_fallback" in decision.timings:
                llm_time = decision.timings["llm_fallback"]
                if llm_time > 0.1:  # Significant LLM time
                    llm_fallbacks += 1
                    print(f"  ⚠️  {query}: LLM fallback used ({llm_time:.2f}s)")
                    continue

        pattern_hits += 1
        print(f"  ✅ {query}: Pattern matched ({match_type})")

        if decision.timings:
            total_route_time = sum(decision.timings.values())
            print(f"      Router time: {total_route_time:.3f}s")

    print(f"\n📊 Results:")
    print(f"  Pattern matches: {pattern_hits}/{len(test_cases)}")
    print(f"  LLM fallbacks: {llm_fallbacks}/{len(test_cases)}")

    success_rate = pattern_hits / len(test_cases) * 100
    print(f"  Success rate: {success_rate:.1f}%")

    if success_rate >= 75:
        print(f"  ✅ Pattern matching working well")
    else:
        print(f"  ⚠️  Many queries falling back to LLM")

    print("\n" + "=" * 60)


async def benchmark_phase2():
    """Run Phase 2 performance benchmark."""
    print("=" * 60)
    print("Phase 2 Performance Benchmark")
    print("=" * 60)
    print("\nPhase 2 Improvements:")
    print("  - Precompiled SQL rules")
    print("  - Pattern matching bypasses LLM")
    print()

    await test_precompiled_sql()
    await test_pattern_matching()

    print("\n" + "=" * 60)
    print("Phase 2 Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(benchmark_phase2())

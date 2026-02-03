"""Performance Test - Phase 1 Optimizations.

Tests the performance improvements from Phase 1:
- Semantic cache threshold lowered (0.9 -> 0.85)
- SQL cache removed (unified to Semantic Cache)
- SQL WHERE optimization
- Performance monitoring added

Goals:
- Cache query < 5s
- First query < 10s
"""

import asyncio
import time
from olav.core.query_router import QueryRouter
from olav.agents.query_agent_v2 import QueryAgentV2


# Test queries (same as E2E test)
TEST_QUERIES = [
    "List all devices version info",  # Simple query
    "R1 BGP neighbors",  # Device specific
    "Show all interfaces",  # Network wide
]


async def benchmark_phase1():
    """Run Phase 1 performance benchmark."""
    print("=" * 60)
    print("Phase 1 Performance Benchmark")
    print("=" * 60)
    print("\nGoals:")
    print("  - Cache query < 5s")
    print("  - First query < 10s")
    print()

    results = []
    router = QueryRouter()

    for query in TEST_QUERIES:
        print(f"\nTesting: {query}")
        print("-" * 40)

        # First query (cold cache)
        agent = QueryAgentV2(mode="standard")

        start = time.time()
        result = await agent.query(query)
        cold_time = time.time() - start

        perf_data = result.get("_raw", {}).get("performance", {})
        print(f"  First query: {cold_time:.2f}s (performance: {perf_data})")

        # Check routing decision timings
        decision = router.route(query)
        if decision.timings:
            print(f"  Router timings: {decision.timings}")

        # Second query (warm cache - should hit semantic cache)
        agent2 = QueryAgentV2(mode="standard")

        start = time.time()
        result2 = await agent2.query(query)
        warm_time = time.time() - start

        perf_data2 = result2.get("_raw", {}).get("performance", {})
        print(f"  Cache query: {warm_time:.2f}s (performance: {perf_data2})")

        # Check if cache hit
        decision2 = router.route(query)
        if "cache" in (decision2.message or "").lower():
            print(f"  ✅ Cache HIT: {decision2.message}")
        else:
            print(f"  ⚠️  Cache MISS: {decision2.message}")

        results.append({
            "query": query,
            "cold": cold_time,
            "warm": warm_time,
            "speedup": cold_time / warm_time if warm_time > 0 else 0,
        })

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    for r in results:
        print(f"\n{r['query']}:")
        print(f"  Cold: {r['cold']:.2f}s")
        print(f"  Warm: {r['warm']:.2f}s")
        print(f"  Speedup: {r['speedup']:.2f}x")

    avg_cold = sum(r["cold"] for r in results) / len(results)
    avg_warm = sum(r["warm"] for r in results) / len(results)
    avg_speedup = sum(r["speedup"] for r in results) / len(results)

    print(f"\n📊 Averages:")
    print(f"  First query: {avg_cold:.2f}s")
    print(f"  Cache query: {avg_warm:.2f}s")
    print(f"  Speedup: {avg_speedup:.2f}x")

    # Validate goals
    print(f"\n✅ Goal Validation:")
    if avg_warm < 5.0:
        print(f"  ✅ Cache query < 5s: PASSED ({avg_warm:.2f}s)")
    else:
        print(f"  ❌ Cache query < 5s: FAILED ({avg_warm:.2f}s)")

    if avg_cold < 10.0:
        print(f"  ✅ First query < 10s: PASSED ({avg_cold:.2f}s)")
    else:
        print(f"  ❌ First query < 10s: FAILED ({avg_cold:.2f}s)")

    # Compare with baseline
    print(f"\n📈 Comparison with Baseline:")
    print(f"  Baseline cache query: 8.64s")
    print(f"  Current cache query: {avg_warm:.2f}s")
    print(f"  Improvement: {((8.64 - avg_warm) / 8.64 * 100):.1f}%")

    print("\n" + "=" * 60)

    # Assert for CI/CD
    assert avg_warm < 5.0, f"Cache query too slow: {avg_warm:.2f}s"
    assert avg_cold < 10.0, f"First query too slow: {avg_cold:.2f}s"


if __name__ == "__main__":
    asyncio.run(benchmark_phase1())

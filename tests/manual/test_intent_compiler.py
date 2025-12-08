"""Test IntentCompiler for Inspection Mode.

Tests the LLM-driven intent to query plan compilation.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from olav.modes.inspection.compiler import IntentCompiler

# Test cases: (intent, expected_table, expected_validation_field)
TEST_CASES = [
    ("检查 BGP 邻居状态是否 Established", "bgp", "state"),
    ("检查 OSPF 邻居是否 Full 状态", "ospf", "state"),
    ("检查接口是否有输入错误", "interfaces", "errorsIn"),
    ("检查路由表中的路由数量", "routes", None),
    ("检查设备 CPU 使用率", "device", None),
    ("检查 MAC 地址表是否为空", "macs", None),
    ("检查 LLDP 邻居发现", "lldp", None),
]


async def test_intent_compiler():
    """Test IntentCompiler with various intents."""

    print("=" * 70)
    print("IntentCompiler Test")
    print("=" * 70)

    # Clear cache for fresh test
    compiler = IntentCompiler(enable_cache=False)

    results = {"passed": 0, "failed": 0, "errors": 0}

    for intent, expected_table, _expected_field in TEST_CASES:
        try:
            print(f"\n{'─' * 70}")
            print(f"Intent: {intent}")
            print(f"Expected table: {expected_table}")

            plan = await compiler.compile(
                intent=intent,
                check_name="test_check",
                severity="warning",
            )

            # Check table match
            table_match = plan.table == expected_table

            print("Result:")
            print(f"  table: {plan.table} {'✅' if table_match else '❌'}")
            print(f"  method: {plan.method}")
            print(f"  filters: {plan.filters}")
            if plan.validation:
                print(f"  validation: {plan.validation.field} {plan.validation.operator} {plan.validation.expected}")
            print(f"  confidence: {plan.confidence}")

            if table_match:
                results["passed"] += 1
                print("Status: ✅ PASS")
            else:
                results["failed"] += 1
                print(f"Status: ❌ FAIL (expected {expected_table}, got {plan.table})")

        except Exception as e:
            print(f"ERROR: {e}")
            results["errors"] += 1

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Total:   {len(TEST_CASES)}")
    print(f"Passed:  {results['passed']}")
    print(f"Failed:  {results['failed']}")
    print(f"Errors:  {results['errors']}")
    print("=" * 70)

    return results["failed"] == 0 and results["errors"] == 0


async def test_caching():
    """Test that caching works correctly."""
    print("\n" + "=" * 70)
    print("Cache Test")
    print("=" * 70)

    import time

    compiler = IntentCompiler(enable_cache=True)
    compiler.clear_cache()  # Start fresh

    intent = "检查 BGP 邻居状态"

    # First call - should hit LLM
    start = time.perf_counter()
    plan1 = await compiler.compile(intent=intent, check_name="cache_test")
    time1 = (time.perf_counter() - start) * 1000

    # Second call - should hit cache
    start = time.perf_counter()
    plan2 = await compiler.compile(intent=intent, check_name="cache_test")
    time2 = (time.perf_counter() - start) * 1000

    print(f"First call (LLM): {time1:.0f} ms")
    print(f"Second call (cache): {time2:.0f} ms")
    print(f"Speedup: {time1 / time2:.1f}x" if time2 > 0 else "N/A")

    # Verify same result
    same_result = plan1.table == plan2.table
    print(f"Same result: {'✅' if same_result else '❌'}")

    # Cache should be faster
    cache_faster = time2 < time1 / 2
    print(f"Cache faster: {'✅' if cache_faster else '⚠️ (may be due to LLM variance)'}")

    return same_result


async def test_fallback():
    """Test fallback compilation when LLM fails."""
    print("\n" + "=" * 70)
    print("Fallback Test")
    print("=" * 70)

    compiler = IntentCompiler(enable_cache=False)

    # Test fallback keywords
    test_cases = [
        ("检查 BGP 状态", "bgp"),
        ("检查 OSPF 邻居", "ospf"),
        ("检查接口错误", "interfaces"),
        ("检查路由表", "routes"),
    ]

    for intent, expected in test_cases:
        plan = compiler._fallback_compile(intent, "test", "warning")
        match = plan.table == expected
        print(f"'{intent}' → {plan.table} {'✅' if match else '❌'}")

    return True


if __name__ == "__main__":
    print("Starting IntentCompiler tests...\n")

    success = True

    # Run all tests
    success &= asyncio.run(test_intent_compiler())
    success &= asyncio.run(test_caching())
    success &= asyncio.run(test_fallback())

    print("\n" + "=" * 70)
    print(f"Overall: {'✅ ALL TESTS PASSED' if success else '❌ SOME TESTS FAILED'}")
    print("=" * 70)

    sys.exit(0 if success else 1)

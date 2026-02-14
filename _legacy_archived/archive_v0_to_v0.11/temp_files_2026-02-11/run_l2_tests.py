#!/usr/bin/env python3
"""
Level 2 测试脚本 - 中等复杂度扩展查询
基于已验证的L1命令，扩展到更复杂场景
"""

import subprocess
import time
from pathlib import Path
from datetime import datetime
import sys

OLAV_ROOT = Path("/home/yhvh/Olav")
EXPORTS_DIR = OLAV_ROOT / "exports"

# L2 Test Cases (预期的P0/P1 - 但部分可能因数据不完整而失败)
L2_TESTS = [
    # P0: 基础扩展
    {
        "id": "L2-P0-001",
        "priority": "P0",
        "name": "设备排序查询",
        "query": "按设备ID或主机名排序列出所有设备",
        "category": "ordering"
    },
    {
        "id": "L2-P0-002",
        "priority": "P0",
        "name": "条件过滤",
        "query": "列出IP地址包含100的所有设备",
        "category": "filtering"
    },
    {
        "id": "L2-P0-003",
        "priority": "P0",
        "name": "多角色统计",
        "query": "统计每个设备角色的数量",
        "category": "grouping"
    },
    {
        "id": "L2-P0-004",
        "priority": "P0",
        "name": "多站点统计",
        "query": "统计每个站点的设备数量",
        "category": "grouping"
    },
    {
        "id": "L2-P0-005",
        "priority": "P0",
        "name": "关联查询简单版",
        "query": "列出每个站点有多少各种角色的设备",
        "category": "join"
    },
    
    # P1: 中等复杂度
    {
        "id": "L2-P1-006",
        "priority": "P1",
        "name": "特定类型设备",
        "query": "找出所有Router类型的设备",
        "category": "filtering"
    },
    {
        "id": "L2-P1-007",
        "priority": "P1",
        "name": "特定站点设备",
        "query": "列出lab站点的所有设备及其角色",
        "category": "filtering"
    },
    {
        "id": "L2-P1-008",
        "priority": "P1",
        "name": "综合条件查询",
        "query": "列出lab站点中所有border角色的设备",
        "category": "multi_filter"
    },
    {
        "id": "L2-P1-009",
        "priority": "P1",
        "name": "设备信息汇总",
        "query": "显示每个设备的详细信息（包括IP、角色、站点）",
        "category": "projection"
    },
    {
        "id": "L2-P1-010",
        "priority": "P1",
        "name": "排序和限制",
        "query": "列出前3个设备及其IP地址",
        "category": "ordering_limit"
    },
    
    # P2: 复杂数据关联 (可能失败 - 因为测试数据不完整)
    {
        "id": "L2-P2-011",
        "priority": "P2",
        "name": "接口数据查询",
        "query": "查询有多少个接口以及每个设备的接口数",
        "category": "data_dependent"
    },
    {
        "id": "L2-P2-012",
        "priority": "P2",
        "name": "流量统计",
        "query": "计算各设备的总流量",
        "category": "data_dependent"
    },
    {
        "id": "L2-P2-013",
        "priority": "P2",
        "name": "拓扑查询",
        "query": "列出所有的网络链接关系",
        "category": "data_dependent"
    },
    {
        "id": "L2-P2-014",
        "priority": "P2",
        "name": "邻接设备",
        "query": "找出与R1相邻的所有设备",
        "category": "topology"
    },
    {
        "id": "L2-P2-015",
        "priority": "P2",
        "name": "配置历史",
        "query": "查询设备的配置变更历史",
        "category": "data_dependent"
    },
]

def run_query(query: str, timeout=60) -> tuple[bool, str, float]:
    """执行Query"""
    start = time.time()
    try:
        result = subprocess.run(
            ["uv", "run", "olav", "query", query],
            cwd=OLAV_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        elapsed = time.time() - start
        return result.returncode == 0, result.stdout + result.stderr, elapsed
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", timeout
    except Exception as e:
        return False, str(e), time.time() - start

def execute_test(test: dict) -> dict:
    """执行单个L2测试"""
    test_id = test["id"]
    query = test["query"]
    
    print(f"\n{'='*70}")
    print(f"🧪 {test_id}: {test['name']}")
    print(f"   Query: {query}")
    print(f"   Category: {test['category']}")
    
    success, output, elapsed = run_query(query)
    
    if not success:
        print(f"   ❌ FAILED (execution error) - {elapsed:.1f}s")
        return {
            "id": test_id,
            "priority": test["priority"],
            "name": test["name"],
            "status": "failed",
            "duration": elapsed,
            "reason": "execution_error"
        }
    
    # Simple verification: non-empty response
    if len(output.strip()) > 50:
        print(f"   ✅ PASSED - {elapsed:.1f}s")
        return {
            "id": test_id,
            "priority": test["priority"],
            "name": test["name"],
            "status": "passed",
            "duration": elapsed,
            "category": test["category"]
        }
    else:
        print(f"   ⚠️  SKIPPED (no data) - {elapsed:.1f}s")
        return {
            "id": test_id,
            "priority": test["priority"],
            "name": test["name"],
            "status": "skipped",
            "duration": elapsed,
            "reason": "no_output"
        }

def main():
    print("\n" + "="*70)
    print("🚀 LEVEL 2 TEST SUITE (中等复杂度查询)")
    print("="*70)
    print(f"总测试数: {len(L2_TESTS)}")
    print(f"分布: {len([t for t in L2_TESTS if t['priority']=='P0'])} P0 + "
          f"{len([t for t in L2_TESTS if t['priority']=='P1'])} P1 + "
          f"{len([t for t in L2_TESTS if t['priority']=='P2'])} P2")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Note: L2包含更复杂的数据关联，部分测试可能因数据不完整而失败")
    
    results = []
    for i, test in enumerate(L2_TESTS, 1):
        print(f"\n[{i}/{len(L2_TESTS)}]")
        result = execute_test(test)
        results.append(result)
        time.sleep(1)  # 测试间隔
    
    # Summary
    print("\n" + "="*70)
    print("📊 TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for r in results if r["status"] == "passed")
    failed = sum(1 for r in results if r["status"] == "failed")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    total = len(results)
    
    print(f"\n✅ PASSED:  {passed}/{total} ({100*passed/total:.0f}%)")
    print(f"❌ FAILED:  {failed}/{total} ({100*failed/total:.0f}%)")
    print(f"⏭️  SKIPPED: {skipped}/{total} ({100*skipped/total:.0f}%)")
    
    # By priority
    for priority in ["P0", "P1", "P2"]:
        p_results = [r for r in results if r.get("priority") == priority]
        p_pass = sum(1 for r in p_results if r["status"] == "passed")
        print(f"\n{priority}: {p_pass}/{len(p_results)} PASSED")
    
    # Category breakdown
    print("\n📂 By Category:")
    categories = {}
    for r in results:
        cat = r.get("category", "unknown")
        if cat not in categories:
            categories[cat] = {"pass": 0, "total": 0}
        categories[cat]["total"] += 1
        if r["status"] == "passed":
            categories[cat]["pass"] += 1
    
    for cat in sorted(categories.keys()):
        stats = categories[cat]
        print(f"  {cat}: {stats['pass']}/{stats['total']}")
    
    # Statistics
    avg_time = sum(r["duration"] for r in results) / len(results) if results else 0
    max_time = max(r["duration"] for r in results) if results else 0
    min_time = min(r["duration"] for r in results) if results else 0
    
    print(f"\n⏱️  Performance:")
    print(f"  Average: {avg_time:.1f}s")
    print(f"  Min: {min_time:.1f}s")
    print(f"  Max: {max_time:.1f}s")
    
    # Comparison with L1
    print(f"\n📈 L1 vs L2:")
    print(f"  L1 Pass Rate: 67% (6/9)")
    print(f"  L2 Pass Rate: {100*passed/total:.0f}% ({passed}/{total})")
    if passed < 6:
        print(f"  ⚠️  L2难度更高，部分失败属正常")
    else:
        print(f"  ✅ L2性能超出预期")
    
    print(f"\n结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return 0 if passed >= 5 else 1

if __name__ == "__main__":
    sys.exit(main())

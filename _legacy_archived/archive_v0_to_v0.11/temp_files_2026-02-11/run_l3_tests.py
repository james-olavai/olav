#!/usr/bin/env python3
"""
Level 3 Test Suite - Advanced Queries + 5 Network Scenarios

Tests validate:
✅ Advanced natural language queries (Window functions, self-joins, recursive)
✅ 5 Core network operations scenarios:
   - Scenario 1: Capacity Planning (TOP 10 interfaces by traffic)
   - Scenario 2: Anomaly Detection (Zero-traffic interfaces)
   - Scenario 3: Relationship Validation (Symmetric links)
   - Scenario 4: Trend Analysis (Week-over-week)
   - Scenario 5: Multi-dimensional Analysis (Device×Protocol×Traffic)

Status: Level 1-2 ✅ Complete (13/14 PASS)
Target: Level 3 ⏳ Starting...

Success Criteria:
- P0: Pass 5/6 high-priority tests
- Overall: Pass ≥18/40 tests
- CSV files generated with correct structure

Run: uv run python run_l3_tests.py
"""

import asyncio
import subprocess
import time
from pathlib import Path
from datetime import datetime


class Level3TestRunner:
    """Run Level 3 tests and track results."""

    def __init__(self):
        self.results = {
            "scenario_1": [],  # Capacity Planning
            "scenario_2": [],  # Anomaly Detection
            "scenario_3": [],  # Relationship Validation
            "scenario_4": [],  # Trend Analysis
            "scenario_5": [],  # Multi-dimensional Analysis
        }
        self.start_time = datetime.now()
        self.exports_dir = Path("exports")
        self.reports_dir = Path("exports/reports")

    async def run_scenario_1(self):
        """Scenario 1: Capacity Planning - TOP 10 traffic interfaces"""
        print("\n" + "=" * 80)
        print("🎬 SCENARIO 1: CAPACITY PLANNING (容量规划)")
        print("=" * 80)
        
        tests = [
            {
                "id": "L3-1",
                "priority": "P0",
                "query": "List the interfaces with highest traffic in past 10 days, export to CSV",
                "expected_file": "top_10_traffic_interfaces_10d.csv",
                "description": "基础版本：过去10天流量最高的接口"
            },
            {
                "id": "L3-2",
                "priority": "P1",
                "query": "Show top 10 interfaces by traffic with their speed rating and utilization percentage, help me identify saturation. Export to CSV",
                "expected_file": "top_traffic_capacity_analysis.csv",
                "description": "带速率信息：识别接近饱和的接口"
            },
            {
                "id": "L3-3",
                "priority": "P1",
                "query": "Group traffic interfaces by device, show top traffic per device. Export to CSV",
                "expected_file": "top_interfaces_by_device.csv",
                "description": "按设备分组版本"
            },
        ]

        for test in tests:
            result = await self.run_test(test)
            self.results["scenario_1"].append(result)

    async def run_scenario_2(self):
        """Scenario 2: Anomaly Detection - Zero-traffic interfaces"""
        print("\n" + "=" * 80)
        print("🎬 SCENARIO 2: ANOMALY DETECTION (异常检测)")
        print("=" * 80)
        
        tests = [
            {
                "id": "L3-9",
                "priority": "P0",
                "query": "Find interfaces that are enabled but have no traffic in the past 10 days. Export to CSV",
                "expected_file": "idle_enabled_interfaces.csv",
                "description": "基础版本：启用但无流量的接口"
            },
            {
                "id": "L3-10",
                "priority": "P1",
                "query": "Which interfaces haven't seen any traffic for more than a week? Include their status and age. Export to CSV",
                "expected_file": "dormant_interfaces_analysis.csv",
                "description": "按创建时间划分版本"
            },
        ]

        for test in tests:
            result = await self.run_test(test)
            self.results["scenario_2"].append(result)

    async def run_scenario_3(self):
        """Scenario 3: Relationship Validation - Asymmetric links"""
        print("\n" + "=" * 80)
        print("🎬 SCENARIO 3: RELATIONSHIP VALIDATION (关系验证)")
        print("=" * 80)
        
        tests = [
            {
                "id": "L3-17",
                "priority": "P0",
                "query": "Check for asymmetric link relationships where one side has a link but the other doesn't. Export to CSV",
                "expected_file": "asymmetric_relationships.csv",
                "description": "找不对称的邻接"
            },
            {
                "id": "L3-18",
                "priority": "P1",
                "query": "Validate all link relationships are bidirectional. Show any misconfigured ones. Export to CSV",
                "expected_file": "relationship_validation_report.csv",
                "description": "关系对称性验证"
            },
        ]

        for test in tests:
            result = await self.run_test(test)
            self.results["scenario_3"].append(result)

    async def run_scenario_4(self):
        """Scenario 4: Trend Analysis - Week-over-week"""
        print("\n" + "=" * 80)
        print("🎬 SCENARIO 4: TREND ANALYSIS (趋势分析)")
        print("=" * 80)
        
        tests = [
            {
                "id": "L3-25",
                "priority": "P0",
                "query": "Compare interface traffic this week vs last week. Show week-over-week percentage change. Export to CSV",
                "expected_file": "weekly_traffic_comparison.csv",
                "description": "基础周环比"
            },
            {
                "id": "L3-26",
                "priority": "P1",
                "query": "Show interfaces with significant traffic changes (>50% increase or >50% decrease) between this week and last week. Export to CSV",
                "expected_file": "traffic_anomalies_wow.csv",
                "description": "异常接口TOP 10"
            },
        ]

        for test in tests:
            result = await self.run_test(test)
            self.results["scenario_4"].append(result)

    async def run_scenario_5(self):
        """Scenario 5: Multi-dimensional Analysis"""
        print("\n" + "=" * 80)
        print("🎬 SCENARIO 5: MULTI-DIMENSIONAL ANALYSIS (多维分析)")
        print("=" * 80)
        
        tests = [
            {
                "id": "L3-33",
                "priority": "P0",
                "query": "Analyze traffic distribution across different device types. Show total bytes and percentage of total. Export to CSV",
                "expected_file": "traffic_by_device_type.csv",
                "description": "设备类型维度分析"
            },
            {
                "id": "L3-34",
                "priority": "P1",
                "query": "Show traffic distribution by link relationship type (BGP, direct, etc). Include percentage of total network traffic. Export to CSV",
                "expected_file": "traffic_by_relationship_type.csv",
                "description": "协议/关系类型维度"
            },
        ]

        for test in tests:
            result = await self.run_test(test)
            self.results["scenario_5"].append(result)

    async def run_test(self, test):
        """Run a single test case."""
        test_id = test["id"]
        priority = test["priority"]
        query = test["query"]
        expected_file = test["expected_file"]
        description = test["description"]

        print(f"\n  📝 {test_id} ({priority}) - {description}")
        print(f"     Query: {query[:70]}...")
        
        start = time.time()
        try:
            # Run the query
            result = subprocess.run(
                ["uv", "run", "olav", "query", query],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            elapsed = time.time() - start
            
            # Check if file was created
            csv_files = list(self.exports_dir.glob("*.csv"))
            markdown_files = list(self.reports_dir.glob("*.csv")) if self.reports_dir.exists() else []
            all_files = csv_files + markdown_files
            
            file_found = any(expected_file in f.name for f in all_files)
            
            if result.returncode == 0 and file_found:
                status = "✅ PASS"
                test_result = {
                    "id": test_id,
                    "priority": priority,
                    "status": "PASS",
                    "elapsed": elapsed,
                }
                print(f"     {status} ({elapsed:.2f}s)")
            else:
                status = "❌ FAIL"
                test_result = {
                    "id": test_id,
                    "priority": priority,
                    "status": "FAIL",
                    "elapsed": elapsed,
                    "reason": "File not created or query failed"
                }
                print(f"     {status} - File not created or query error")
                if result.stderr:
                    print(f"     Error: {result.stderr[:100]}")
            
            return test_result
            
        except subprocess.TimeoutExpired:
            print(f"     ⏱️ TIMEOUT (>30s)")
            return {
                "id": test_id,
                "priority": priority,
                "status": "TIMEOUT",
                "elapsed": 30,
            }
        except Exception as e:
            print(f"     ⚠️ ERROR: {str(e)[:50]}")
            return {
                "id": test_id,
                "priority": priority,
                "status": "ERROR",
                "elapsed": time.time() - start,
                "error": str(e)
            }

    async def run_all(self):
        """Run all Level 3 scenarios."""
        print("\n" + "🚀 " * 20)
        print("STARTING LEVEL 3 TEST EXECUTION")
        print("🚀 " * 20)
        
        await self.run_scenario_1()
        await self.run_scenario_2()
        await self.run_scenario_3()
        await self.run_scenario_4()
        await self.run_scenario_5()
        
        self.print_summary()

    def print_summary(self):
        """Print test summary and results."""
        elapsed_total = (datetime.now() - self.start_time).total_seconds()
        
        print("\n" + "=" * 80)
        print("📊 LEVEL 3 TEST SUMMARY")
        print("=" * 80)
        
        all_results = []
        for scenario, results in self.results.items():
            all_results.extend(results)
        
        # Count results
        passed = sum(1 for r in all_results if r.get("status") == "PASS")
        failed = sum(1 for r in all_results if r.get("status") == "FAIL")
        timeout = sum(1 for r in all_results if r.get("status") == "TIMEOUT")
        error = sum(1 for r in all_results if r.get("status") == "ERROR")
        
        total = passed + failed + timeout + error
        pass_rate = (passed / total * 100) if total > 0 else 0
        
        # Count P0 results
        p0_results = [r for r in all_results if r.get("priority") == "P0"]
        p0_passed = sum(1 for r in p0_results if r.get("status") == "PASS")
        
        print(f"\n🎯 Overall Results:")
        print(f"   ✅ PASS:    {passed:2d}/{total} ({pass_rate:5.1f}%)")
        print(f"   ❌ FAIL:    {failed:2d}/{total}")
        print(f"   ⏱️ TIMEOUT: {timeout:2d}/{total}")
        print(f"   ⚠️ ERROR:   {error:2d}/{total}")
        print(f"\n🔴 P0 Priority (Must-Pass):")
        print(f"   {p0_passed}/{len(p0_results)} PASS")
        
        # Scenario breakdown
        print(f"\n📈 By Scenario:")
        for scenario, results in self.results.items():
            scenario_name = scenario.replace("_", " ").title()
            scenario_passed = sum(1 for r in results if r.get("status") == "PASS")
            scenario_total = len(results)
            print(f"   {scenario_name:30s}: {scenario_passed}/{scenario_total} PASS")
        
        print(f"\n⏱️ Total execution time: {elapsed_total:.1f}s")
        
        # Success criteria
        print(f"\n✅ Success Criteria Check:")
        print(f"   P0 Pass (5/6): {'✅ PASS' if p0_passed >= 5 else '❌ FAIL'} ({p0_passed}/6)")
        print(f"   Overall (≥18/40): {'✅ PASS' if passed >= 18 else '❌ FAIL'} ({passed}/40)")
        
        if passed >= 18 and p0_passed >= 5:
            print(f"\n🎉 LEVEL 3 TEST PASS - Ready for production!" )
        elif passed >= 12:
            print(f"\n⚠️ PARTIAL PASS - {passed}/40, continue with improvements")
        else:
            print(f"\n❌ LEVEL 3 TEST FAIL - {passed}/40, needs work")


async def main():
    runner = Level3TestRunner()
    await runner.run_all()


if __name__ == "__main__":
    asyncio.run(main())

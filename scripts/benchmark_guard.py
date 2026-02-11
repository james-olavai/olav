"""
Performance Benchmarking Script for Guard Router

Purpose:
  Measure performance improvements from Guard routing
  Compare Guard-enabled vs Guard-disabled execution
  Generate detailed performance reports

Targets:
  - Simple queries: 12s → <5s (58% improvement)
  - Expert queries: 12s → 8-12s (no change expected, same orchestrator)
  - Cache hits: <100ms latency improvement
  - Overall: >30% average improvement

Usage:
  python scripts/benchmark_guard.py
  python scripts/benchmark_guard.py --queries simple --iterations 10
"""

import time
import json
import sys
from pathlib import Path
from typing import Callable
from dataclasses import dataclass

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from olav.agents.guard import get_guard, RouteCode
from olav.agents.orchestrator_v2 import orchestrate_with_guard, orchestrate_query_with_routing
from olav.agents.orchestrator import orchestrate_query_sync
from config.settings import settings


# ════════════════════════════════════════════════════════════════════════════
# Benchmark Configuration
# ════════════════════════════════════════════════════════════════════════════


@dataclass
class BenchmarkResult:
    """Single benchmark result."""
    query: str
    route: str
    with_guard_ms: float
    without_guard_ms: float
    improvement_percent: float
    cache_hit: bool = False
    
    def __str__(self) -> str:
        cache_str = " (cache hit)" if self.cache_hit else ""
        return (f"Query: {self.query[:40]:<40} | "
                f"Route: {self.route:<12} | "
                f"Guard: {self.with_guard_ms:>6.1f}ms | "
                f"Baseline: {self.without_guard_ms:>6.1f}ms | "
                f"Improvement: {self.improvement_percent:>6.1f}%{cache_str}")


class GuardBenchmark:
    """Guard performance benchmarking suite."""
    
    # Test queries organized by category
    TEST_QUERIES = {
        "simple": [
            "count all devices",
            "有多少个设备?",
            "list device names",
            "show all interfaces",
            "how many routers?",
        ],
        "cli": [
            "get current device status",
            "show running config",
            "real-time bandwidth",
            "current interface status",
            "检查实时状态",
        ],
        "expert": [
            "which devices have errors?",
            "analyze connectivity issues",
            "diagnose network problems",
            "为什么连接不稳定?",
            "root cause analysis",
        ],
        "multi_agent": [
            "is netbox consistent with database?",
            "compare configuration snapshots",
            "verify device consistency",
            "netbox vs database",
            "snapshot and live comparison",
        ],
    }
    
    def __init__(self, output_dir: Path = None):
        """Initialize benchmark."""
        self.output_dir = output_dir or PROJECT_ROOT / "exports" / "benchmarks"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: list[BenchmarkResult] = []
    
    def run_query(self, query: str, use_guard: bool) -> tuple[float, str]:
        """Run single query and measure latency.
        
        Args:
            query: Query to execute
            use_guard: Whether to use Guard routing
            
        Returns:
            (latency_ms, route_type)
        """
        start = time.perf_counter()
        
        try:
            if use_guard:
                result = orchestrate_with_guard(query)
            else:
                result = orchestrate_query_sync(query)
            
            elapsed_ms = (time.perf_counter() - start) * 1000
            route = result.get("route", "unknown")
            
            return elapsed_ms, route
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            print(f"  ⚠️  Error: {e}")
            return elapsed_ms, "error"
    
    def benchmark_query(self, query: str, iterations: int = 3) -> BenchmarkResult:
        """Benchmark single query with Guard on/off.
        
        Args:
            query: Query to benchmark
            iterations: Number of runs to average
            
        Returns:
            BenchmarkResult with performance metrics
        """
        print(f"\n  📊 Benchmarking: {query[:50]}")
        
        # Run with Guard disabled
        without_guard_times = []
        for i in range(iterations):
            elapsed, _ = self.run_query(query, use_guard=False)
            without_guard_times.append(elapsed)
            print(f"    Run {i+1} (no Guard): {elapsed:.1f}ms")
        
        without_guard_avg = sum(without_guard_times) / len(without_guard_times)
        
        # Run with Guard enabled (first run is cache miss, second might hit)
        with_guard_times = []
        for i in range(iterations):
            elapsed, route = self.run_query(query, use_guard=True)
            with_guard_times.append(elapsed)
            cache_status = " (cache)" if i > 0 else " (miss)"
            print(f"    Run {i+1} (Guard):    {elapsed:.1f}ms{cache_status}")
        
        with_guard_avg = sum(with_guard_times) / len(with_guard_times)
        
        # Calculate improvement
        improvement = (without_guard_avg - with_guard_avg) / without_guard_avg * 100
        
        result = BenchmarkResult(
            query=query,
            route=route,
            with_guard_ms=with_guard_avg,
            without_guard_ms=without_guard_avg,
            improvement_percent=improvement,
            cache_hit=len(with_guard_times) > 1 and with_guard_times[1] < with_guard_times[0]
        )
        
        self.results.append(result)
        return result
    
    def run_benchmarks(self, query_types: list[str] = None, iterations: int = 2):
        """Run full benchmark suite.
        
        Args:
            query_types: Types of queries to benchmark (default: all)
            iterations: Iterations per query
        """
        if query_types is None:
            query_types = list(self.TEST_QUERIES.keys())
        
        print("\n" + "="*80)
        print("🧪 GUARD PERFORMANCE BENCHMARK")
        print("="*80)
        print(f"Configuration:")
        print(f"  • Guard enabled: {settings.agent.enable_guard_routing}")
        print(f"  • Cache TTL: {settings.agent.guard_cache_ttl}s")
        print(f"  • Confidence threshold: {settings.agent.guard_confidence_threshold}")
        print(f"  • Iterations per query: {iterations}")
        print("="*80)
        
        for query_type in query_types:
            queries = self.TEST_QUERIES.get(query_type, [])
            if not queries:
                continue
            
            print(f"\n📍 {query_type.upper()} Queries ({len(queries)} variants)")
            print("-" * 80)
            
            category_results = []
            for query in queries:
                try:
                    result = self.benchmark_query(query, iterations=iterations)
                    category_results.append(result)
                except Exception as e:
                    print(f"    ❌ Query failed: {e}")
            
            # Summary for category
            if category_results:
                avg_improvement = sum(r.improvement_percent for r in category_results) / len(category_results)
                avg_guard = sum(r.with_guard_ms for r in category_results) / len(category_results)
                avg_baseline = sum(r.without_guard_ms for r in category_results) / len(category_results)
                
                print("\n  📊 Category Summary:")
                print(f"    Average without Guard: {avg_baseline:.1f}ms")
                print(f"    Average with Guard:    {avg_guard:.1f}ms")
                print(f"    Average improvement:   {avg_improvement:.1f}%")
    
    def print_report(self):
        """Print detailed benchmark report."""
        if not self.results:
            print("No results to report")
            return
        
        print("\n" + "="*130)
        print("📊 DETAILED BENCHMARK RESULTS")
        print("="*130)
        
        # Group by route
        by_route = {}
        for result in self.results:
            if result.route not in by_route:
                by_route[result.route] = []
            by_route[result.route].append(result)
        
        # Print results by route
        for route in sorted(by_route.keys()):
            results = by_route[route]
            print(f"\n{route} Route ({len(results)} queries)")
            print("-" * 130)
            
            for result in results:
                print(result)
            
            # Route summary
            avg_with_guard = sum(r.with_guard_ms for r in results) / len(results)
            avg_without_guard = sum(r.without_guard_ms for r in results) / len(results)
            avg_improvement = sum(r.improvement_percent for r in results) / len(results)
            
            print(f"\nRoute Summary:")
            print(f"  Average latency (Guard):     {avg_with_guard:.1f}ms")
            print(f"  Average latency (baseline):  {avg_without_guard:.1f}ms")
            print(f"  Average improvement:         {avg_improvement:.1f}%")
        
        # Overall summary
        print("\n" + "="*130)
        print("🎯 OVERALL SUMMARY")
        print("="*130)
        
        total_with_guard = sum(r.with_guard_ms for r in self.results) / len(self.results)
        total_without_guard = sum(r.without_guard_ms for r in self.results) / len(self.results)
        total_improvement = sum(r.improvement_percent for r in self.results) / len(self.results)
        
        print(f"Total queries benchmarked:     {len(self.results)}")
        print(f"Average latency (no Guard):    {total_without_guard:.1f}ms")
        print(f"Average latency (with Guard):  {total_with_guard:.1f}ms")
        print(f"Average improvement:           {total_improvement:.1f}%")
        
        # Performance targets
        print(f"\n📍 Performance Targets:")
        target_simple_ms = 5000  # 5 seconds
        target_improvement = 30  # 30% minimum
        
        print(f"  ✓ Target: SIMPLE queries <5s (currently avg {total_with_guard:.1f}ms)")
        print(f"  ✓ Target: >30% improvement (currently {total_improvement:.1f}%)")
        
        if total_improvement >= target_improvement:
            print(f"\n✅ Performance target achieved: {total_improvement:.1f}% > {target_improvement}%")
        else:
            print(f"\n⚠️  Performance improvement: {total_improvement:.1f}% < {target_improvement}% target")
    
    def save_results(self, filename: str = "guard_benchmark.json"):
        """Save results to JSON file."""
        results_data = [
            {
                "query": r.query,
                "route": r.route,
                "with_guard_ms": r.with_guard_ms,
                "without_guard_ms": r.without_guard_ms,
                "improvement_percent": r.improvement_percent,
                "cache_hit": r.cache_hit,
            }
            for r in self.results
        ]
        
        output_file = self.output_dir / filename
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Results saved to: {output_file}")
        return output_file
    
    def compare_with_previous(self, baseline_file: Path = None):
        """Compare with previous benchmark results."""
        if baseline_file is None:
            baseline_file = self.output_dir / "guard_benchmark_baseline.json"
        
        if not baseline_file.exists():
            print(f"\n⚠️  No baseline to compare: {baseline_file}")
            return
        
        print(f"\n📊 Comparing with baseline: {baseline_file.name}")
        
        with open(baseline_file, "r", encoding="utf-8") as f:
            baseline = json.load(f)
        
        # Simple comparison
        baseline_improvement = sum(b["improvement_percent"] for b in baseline) / len(baseline)
        current_improvement = sum(r.improvement_percent for r in self.results) / len(self.results)
        
        print(f"  Baseline improvement:  {baseline_improvement:.1f}%")
        print(f"  Current improvement:   {current_improvement:.1f}%")
        print(f"  Difference:            {current_improvement - baseline_improvement:+.1f}%")


def main():
    """Run benchmark CLI."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Guard Router Performance Benchmark")
    parser.add_argument(
        "--types",
        choices=["simple", "cli", "expert", "multi_agent", "all"],
        default="simple",
        help="Query types to benchmark (default: simple)"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=2,
        help="Iterations per query (default: 2)"
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save results to JSON"
    )
    parser.add_argument(
        "--compare",
        type=Path,
        help="Compare with baseline file"
    )
    
    args = parser.parse_args()
    
    # Determine query types
    query_types = ["simple", "cli", "expert", "multi_agent"] if args.types == "all" else [args.types]
    
    # Run benchmark
    benchmark = GuardBenchmark()
    benchmark.run_benchmarks(query_types=query_types, iterations=args.iterations)
    benchmark.print_report()
    
    if args.save:
        benchmark.save_results()
    
    if args.compare:
        benchmark.compare_with_previous(args.compare)


if __name__ == "__main__":
    main()

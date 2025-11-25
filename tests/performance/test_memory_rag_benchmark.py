"""
Performance benchmarking for Memory RAG optimization.

This script measures the impact of episodic memory RAG on FastPathStrategy:
- Baseline: Standard LLM parameter extraction (no memory)
- Optimized: Memory RAG with historical pattern reuse

Metrics:
- P50, P95, P99 latencies
- Memory hit rate
- LLM call reduction percentage
- End-to-end execution time

Expected results: 30-50% latency reduction when memory hits occur.
"""

import asyncio
import time
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from olav.strategies.fast_path import FastPathStrategy
from olav.tools.base import ToolOutput, ToolRegistry


@pytest.fixture(autouse=True)
def clear_tool_registry():
    """Clear ToolRegistry singleton before and after each test."""
    ToolRegistry._tools = {}
    yield
    ToolRegistry._tools = {}


class BenchmarkMetrics:
    """Collect and analyze benchmark metrics."""
    
    def __init__(self):
        self.latencies: List[float] = []
        self.llm_call_counts: List[int] = []
        self.memory_hits = 0
        self.memory_misses = 0
        self.total_queries = 0
    
    def record_execution(
        self,
        latency_ms: float,
        llm_calls: int,
        memory_hit: bool = False,
    ):
        """Record single execution metrics."""
        self.latencies.append(latency_ms)
        self.llm_call_counts.append(llm_calls)
        if memory_hit:
            self.memory_hits += 1
        else:
            self.memory_misses += 1
        self.total_queries += 1
    
    def get_percentile(self, percentile: int) -> float:
        """Calculate latency percentile."""
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        index = int(len(sorted_latencies) * percentile / 100)
        return sorted_latencies[min(index, len(sorted_latencies) - 1)]
    
    @property
    def p50(self) -> float:
        """Median latency."""
        return self.get_percentile(50)
    
    @property
    def p95(self) -> float:
        """95th percentile latency."""
        return self.get_percentile(95)
    
    @property
    def p99(self) -> float:
        """99th percentile latency."""
        return self.get_percentile(99)
    
    @property
    def mean_latency(self) -> float:
        """Average latency."""
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0.0
    
    @property
    def memory_hit_rate(self) -> float:
        """Percentage of queries that hit memory."""
        if self.total_queries == 0:
            return 0.0
        return (self.memory_hits / self.total_queries) * 100
    
    @property
    def avg_llm_calls(self) -> float:
        """Average LLM calls per query."""
        return sum(self.llm_call_counts) / len(self.llm_call_counts) if self.llm_call_counts else 0.0
    
    def summary(self) -> Dict:
        """Generate summary report."""
        return {
            "total_queries": self.total_queries,
            "mean_latency_ms": round(self.mean_latency, 2),
            "p50_latency_ms": round(self.p50, 2),
            "p95_latency_ms": round(self.p95, 2),
            "p99_latency_ms": round(self.p99, 2),
            "memory_hits": self.memory_hits,
            "memory_misses": self.memory_misses,
            "memory_hit_rate_pct": round(self.memory_hit_rate, 2),
            "avg_llm_calls_per_query": round(self.avg_llm_calls, 2),
        }


@pytest.fixture
def mock_tool_registry():
    """Mock tool registry with SuzieQ query tool."""
    registry = ToolRegistry()
    registry._tools = {}  # Clear registry
    
    mock_tool = MagicMock()
    mock_tool.name = "suzieq_query"
    mock_tool.execute = AsyncMock(return_value=ToolOutput(
        source="suzieq_query",
        device="R1",
        data=[
            {"hostname": "R1", "neighbor": "10.0.0.2", "state": "Established"},
            {"hostname": "R1", "neighbor": "10.0.0.3", "state": "Idle"},
        ],
        metadata={"table": "bgp", "elapsed_ms": 50},
        error=None,
    ))
    
    registry.register(mock_tool)
    return registry


@pytest.fixture
def mock_llm_with_tracking():
    """Mock LLM that tracks call count."""
    call_count = {"count": 0}
    
    async def llm_invoke(messages):
        call_count["count"] += 1
        
        # First call: parameter extraction
        if call_count["count"] % 2 == 1:
            return AIMessage(content="""{
                "tool": "suzieq_query",
                "parameters": {"table": "bgp", "hostname": "R1"},
                "confidence": 0.95,
                "reasoning": "BGP neighbor query"
            }""")
        
        # Second call: answer formatting
        return AIMessage(content="""{
            "answer": "R1 has 2 BGP neighbors: 10.0.0.2 (Established), 10.0.0.3 (Idle)",
            "data_used": ["neighbor", "state"],
            "confidence": 0.95
        }""")
    
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=llm_invoke)
    mock_llm.call_count = call_count
    
    return mock_llm


@pytest.fixture
def benchmark_queries():
    """Set of queries for benchmarking."""
    return [
        # Repeated queries (should hit memory after first execution)
        "查询 R1 的 BGP 邻居状态",
        "查询 R1 的 BGP 邻居状态",
        "查询 R1 的 BGP 邻居状态",
        
        # Similar queries (should have high similarity)
        "查询 R1 BGP 状态",
        "查询 R1 BGP 邻居",
        
        # Unique queries (memory miss)
        "查询 R2 的接口状态",
        "查询 R3 的路由表",
        "查询 R4 的 OSPF 邻居",
    ]


async def run_benchmark(
    strategy: FastPathStrategy,
    queries: List[str],
    track_llm_calls: bool = True,
) -> BenchmarkMetrics:
    """Run benchmark with given strategy configuration."""
    metrics = BenchmarkMetrics()
    
    for query in queries:
        # Reset LLM call counter
        if hasattr(strategy, "llm") and hasattr(strategy.llm, "call_count"):
            initial_calls = strategy.llm.call_count["count"]
        else:
            initial_calls = 0
        
        # Measure execution time
        start_time = time.perf_counter()
        
        try:
            result = await strategy.execute(query)
            
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000
            
            # Calculate LLM calls for this query
            if hasattr(strategy, "llm") and hasattr(strategy.llm, "call_count"):
                llm_calls = strategy.llm.call_count["count"] - initial_calls
            else:
                llm_calls = 2  # Assume standard 2 calls (extraction + formatting)
            
            # Detect memory hit (1 LLM call means memory was used, skipped extraction)
            memory_hit = llm_calls < 2 if strategy.enable_memory_rag else False
            
            metrics.record_execution(
                latency_ms=latency_ms,
                llm_calls=llm_calls,
                memory_hit=memory_hit,
            )
        
        except Exception as e:
            print(f"Query failed: {query}, Error: {e}")
            continue
    
    return metrics


@pytest.mark.asyncio
async def test_baseline_performance(mock_llm_with_tracking, mock_tool_registry, benchmark_queries):
    """Benchmark baseline performance WITHOUT Memory RAG."""
    
    # Create strategy with Memory RAG disabled
    strategy = FastPathStrategy(
        llm=mock_llm_with_tracking,
        tool_registry=mock_tool_registry,
        enable_memory_rag=False,  # Baseline: no memory optimization
        confidence_threshold=0.7,
    )
    
    metrics = await run_benchmark(strategy, benchmark_queries)
    
    print("\n=== BASELINE (No Memory RAG) ===")
    print(f"Total Queries: {metrics.total_queries}")
    print(f"Mean Latency: {metrics.mean_latency:.2f} ms")
    print(f"P50 Latency: {metrics.p50:.2f} ms")
    print(f"P95 Latency: {metrics.p95:.2f} ms")
    print(f"P99 Latency: {metrics.p99:.2f} ms")
    print(f"Avg LLM Calls: {metrics.avg_llm_calls:.2f}")
    print(f"Memory Hit Rate: {metrics.memory_hit_rate:.2f}%")
    
    # Assertions for baseline
    assert metrics.total_queries == len(benchmark_queries)
    assert metrics.memory_hit_rate == 0.0  # No memory in baseline
    assert metrics.avg_llm_calls == 2.0  # Always 2 calls (extraction + formatting)


@pytest.mark.asyncio
async def test_optimized_performance(mock_llm_with_tracking, mock_tool_registry, benchmark_queries):
    """Benchmark optimized performance WITH Memory RAG."""
    
    # Mock episodic memory tool with historical patterns
    mock_episodic_memory_tool = MagicMock()
    
    # Simulate memory returning historical pattern for repeated queries
    async def memory_search(intent: str, max_results: int = 5, only_successful: bool = True, **kwargs):
        # First query: no memory (cold start)
        # Subsequent identical queries: return historical pattern
        if intent == "查询 R1 的 BGP 邻居状态":
            # Simulate memory learning after first execution
            if not hasattr(memory_search, "seen_queries"):
                memory_search.seen_queries = set()
            
            if intent in memory_search.seen_queries:
                # Memory hit: return historical pattern
                return ToolOutput(
                    source="episodic_memory_search",
                    device="unknown",
                    data=[{
                        "intent": intent,
                        "tool_used": "suzieq_query",
                        "parameters": {"table": "bgp", "hostname": "R1"},
                        "xpath": "table=bgp, hostname=R1",
                        "success": True,
                        "execution_time_ms": 120,
                    }],
                    metadata={},
                    error=None,
                )
            else:
                # First time seeing this query
                memory_search.seen_queries.add(intent)
                return ToolOutput(
                    source="episodic_memory_search",
                    device="unknown",
                    data=[],  # No historical data yet
                    metadata={},
                    error=None,
                )
        
        # Similar queries get partial matches
        if "BGP" in intent and "R1" in intent:
            return ToolOutput(
                source="episodic_memory_search",
                device="unknown",
                data=[{
                    "intent": "查询 R1 的 BGP 邻居状态",
                    "tool_used": "suzieq_query",
                    "parameters": {"table": "bgp", "hostname": "R1"},
                    "xpath": "table=bgp, hostname=R1",
                    "success": True,
                    "execution_time_ms": 120,
                }],
                metadata={},
                error=None,
            )
        
        # Unique queries: no memory
        return ToolOutput(
            source="episodic_memory_search",
            device="unknown",
            data=[],
            metadata={},
            error=None,
        )
    
    mock_episodic_memory_tool.execute = AsyncMock(side_effect=memory_search)
    
    # Create strategy with Memory RAG enabled
    strategy = FastPathStrategy(
        llm=mock_llm_with_tracking,
        tool_registry=mock_tool_registry,
        enable_memory_rag=True,  # Optimized: memory enabled
        episodic_memory_tool=mock_episodic_memory_tool,
        confidence_threshold=0.7,
    )
    
    metrics = await run_benchmark(strategy, benchmark_queries)
    
    print("\n=== OPTIMIZED (With Memory RAG) ===")
    print(f"Total Queries: {metrics.total_queries}")
    print(f"Mean Latency: {metrics.mean_latency:.2f} ms")
    print(f"P50 Latency: {metrics.p50:.2f} ms")
    print(f"P95 Latency: {metrics.p95:.2f} ms")
    print(f"P99 Latency: {metrics.p99:.2f} ms")
    print(f"Avg LLM Calls: {metrics.avg_llm_calls:.2f}")
    print(f"Memory Hit Rate: {metrics.memory_hit_rate:.2f}%")
    
    # Assertions for optimized version
    assert metrics.total_queries == len(benchmark_queries)
    assert metrics.memory_hit_rate > 0.0  # Should have some memory hits
    assert metrics.avg_llm_calls < 2.0  # Less than 2 calls on average (memory skips extraction)


@pytest.mark.asyncio
async def test_memory_rag_comparison(mock_llm_with_tracking, mock_tool_registry, benchmark_queries):
    """Compare baseline vs optimized and calculate improvement metrics."""
    
    # Run baseline benchmark
    strategy_baseline = FastPathStrategy(
        llm=mock_llm_with_tracking,
        tool_registry=mock_tool_registry,
        enable_memory_rag=False,
        confidence_threshold=0.7,
    )
    
    # Reset LLM call counter
    mock_llm_with_tracking.call_count["count"] = 0
    
    baseline_metrics = await run_benchmark(strategy_baseline, benchmark_queries)
    
    # Run optimized benchmark with fresh LLM counter
    mock_llm_with_tracking.call_count["count"] = 0
    
    # Mock episodic memory (same as test_optimized_performance)
    mock_episodic_memory_tool = MagicMock()
    
    async def memory_search(intent: str, max_results: int = 5, only_successful: bool = True, **kwargs):
        if intent == "查询 R1 的 BGP 邻居状态":
            if not hasattr(memory_search, "seen_queries"):
                memory_search.seen_queries = set()
            
            if intent in memory_search.seen_queries:
                return ToolOutput(
                    source="episodic_memory_search",
                    device="unknown",
                    data=[{
                        "intent": intent,
                        "tool_used": "suzieq_query",
                        "parameters": {"table": "bgp", "hostname": "R1"},
                        "xpath": "table=bgp, hostname=R1",
                        "success": True,
                        "execution_time_ms": 120,
                    }],
                    metadata={},
                    error=None,
                )
            else:
                memory_search.seen_queries.add(intent)
                return ToolOutput(
                    source="episodic_memory_search",
                    device="unknown",
                    data=[],
                    metadata={},
                    error=None,
                )
        
        if "BGP" in intent and "R1" in intent:
            return ToolOutput(
                source="episodic_memory_search",
                device="unknown",
                data=[{
                    "intent": "查询 R1 的 BGP 邻居状态",
                    "tool_used": "suzieq_query",
                    "parameters": {"table": "bgp", "hostname": "R1"},
                    "xpath": "table=bgp, hostname=R1",
                    "success": True,
                    "execution_time_ms": 120,
                }],
                metadata={},
                error=None,
            )
        
        return ToolOutput(
            source="episodic_memory_search",
            device="unknown",
            data=[],
            metadata={},
            error=None,
        )
    
    mock_episodic_memory_tool.execute = AsyncMock(side_effect=memory_search)
    
    strategy_optimized = FastPathStrategy(
        llm=mock_llm_with_tracking,
        tool_registry=mock_tool_registry,
        enable_memory_rag=True,
        episodic_memory_tool=mock_episodic_memory_tool,
        confidence_threshold=0.7,
    )
    
    optimized_metrics = await run_benchmark(strategy_optimized, benchmark_queries)
    
    # Calculate improvement percentages
    latency_improvement_pct = (
        (baseline_metrics.mean_latency - optimized_metrics.mean_latency) / baseline_metrics.mean_latency * 100
    )
    llm_call_reduction_pct = (
        (baseline_metrics.avg_llm_calls - optimized_metrics.avg_llm_calls) / baseline_metrics.avg_llm_calls * 100
    )
    
    print("\n=== PERFORMANCE COMPARISON ===")
    print(f"\nBaseline (No Memory RAG):")
    print(f"  Mean Latency: {baseline_metrics.mean_latency:.2f} ms")
    print(f"  P50: {baseline_metrics.p50:.2f} ms")
    print(f"  P95: {baseline_metrics.p95:.2f} ms")
    print(f"  Avg LLM Calls: {baseline_metrics.avg_llm_calls:.2f}")
    
    print(f"\nOptimized (With Memory RAG):")
    print(f"  Mean Latency: {optimized_metrics.mean_latency:.2f} ms")
    print(f"  P50: {optimized_metrics.p50:.2f} ms")
    print(f"  P95: {optimized_metrics.p95:.2f} ms")
    print(f"  Avg LLM Calls: {optimized_metrics.avg_llm_calls:.2f}")
    print(f"  Memory Hit Rate: {optimized_metrics.memory_hit_rate:.2f}%")
    
    print(f"\nImprovements:")
    print(f"  Latency Reduction: {latency_improvement_pct:.2f}%")
    print(f"  LLM Call Reduction: {llm_call_reduction_pct:.2f}%")
    
    # Assertions
    assert optimized_metrics.memory_hit_rate > 0.0
    assert optimized_metrics.avg_llm_calls < baseline_metrics.avg_llm_calls
    
    # Note: We don't assert latency improvement here because mock execution is too fast
    # to show realistic time differences. In production with real LLM calls, we'd expect
    # 30-50% latency reduction for memory hits.
    
    return {
        "baseline": baseline_metrics.summary(),
        "optimized": optimized_metrics.summary(),
        "latency_improvement_pct": round(latency_improvement_pct, 2),
        "llm_call_reduction_pct": round(llm_call_reduction_pct, 2),
    }


if __name__ == "__main__":
    """Run benchmarks standalone."""
    pytest.main([__file__, "-v", "-s"])

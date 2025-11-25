"""
Execution Strategies Package.

This package implements different execution strategies for OLAV workflows:

- FastPathStrategy: Single-shot function calling for simple queries (no agent loop)
- DeepPathStrategy: Hypothesis-driven loop for complex diagnostics (iterative reasoning)
- BatchPathStrategy: YAML-driven inspection with parallel execution (deterministic validation)

Each strategy optimizes for different query characteristics:
- Fast: Low latency, high certainty (SuzieQ table lookup)
- Deep: High complexity, root cause analysis (multi-source validation)
- Batch: High volume, compliance checks (zero-hallucination logic)
"""

from .fast_path import FastPathStrategy
from .deep_path import DeepPathStrategy
from .batch_path import BatchPathStrategy
from .selector import StrategySelector, StrategyDecision, create_strategy_selector

__all__ = [
    "FastPathStrategy",
    "DeepPathStrategy",
    "BatchPathStrategy",
    "StrategySelector",
    "StrategyDecision",
    "create_strategy_selector",
]

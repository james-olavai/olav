"""Orchestrator Agent - SubAgent-based Meta-Agent (v0.11.1)

REFACTORED: Phase 2.1 Code Simplification
Separated 1,681 lines into 4 focused modules:

- router.py (270 lines): Factory functions and SubAgent creation
- dependency_executor.py (180 lines): Dependency graph and collaborative execution  
- query_orchestrator.py (550 lines): Synchronous query execution engine
- orchestrator.py (100 lines): Unified public API and re-exports

This module provides backward-compatible exports for all orchestrator functionality.

The Orchestrator is the central coordinator that:
1. Routes user queries to appropriate specialist SubAgents
2. Executes ReAct loops for complex multi-step tasks
3. Aggregates and synthesizes results from multiple specialists

Architecture (Refactored Phase 2.1):
- Tier 0: Cache (instant responses)
- Tier 1: SubAgent Router (declarative specialist dispatch)
- Tier 2: ReAct Orchestrator (multi-step reasoning)

Migration: v0.11.0 -> v0.11.1
- Separated router, dependency executor, and query execution into dedicated modules
- Maintains backward compatibility through re-exports
- Reduced orchestrator.py from 1,681 lines to ~100 lines
- Total savings: ~1,500 lines of dead code and duplicate logic
"""

from __future__ import annotations

import logging

# Re-export all public APIs for backward compatibility
from olav.agents.dependency_executor import (
    _build_dependency_graph,
    _execute_with_dependencies_order,
    _parse_collaborative_mode,
    _topological_sort,
)
from olav.agents.query_orchestrator import (
    format_query_result,
    orchestrate_query,
    orchestrate_query_sync,
    parse_lim_response_for_sql,
)
from olav.agents.router import (
    create_collaborative_orchestrator,
    create_orchestrator,
    create_planning_orchestrator,
)

logger = logging.getLogger(__name__)

# Public API exports - all original functionality preserved
__all__ = [
    # Router factory functions
    "create_orchestrator",
    "create_collaborative_orchestrator",
    "create_planning_orchestrator",
    # Query execution
    "orchestrate_query",
    "orchestrate_query_sync",
    "parse_lim_response_for_sql",
    "format_query_result",
    # Dependency functions
    "_parse_collaborative_mode",
    "_build_dependency_graph",
    "_topological_sort",
    "_execute_with_dependencies_order",
]

"""Tools module.

Note: This module previously used lazy imports for langchain tools.
All tools have been migrated to direct imports where needed.

Exported Tools (Phase 5B.3+):
- aggregate_inspection_results() from aggregation.py (Reduce phase)
- execute_commands_in_parallel() from batch_executor.py (Map helper)
"""

from .aggregation import aggregate_inspection_results, identify_anomalies
from .batch_executor import (
    execute_commands_in_parallel,
    batch_execute_with_timeout,
    parallel_health_check,
)

__all__ = [
    # Aggregation/Reduce phase
    "aggregate_inspection_results",
    "identify_anomalies",
    # Batch execution/Map phase
    "execute_commands_in_parallel",
    "batch_execute_with_timeout",
    "parallel_health_check",
]

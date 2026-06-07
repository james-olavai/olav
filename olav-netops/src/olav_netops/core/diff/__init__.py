"""Snapshot diff helpers (Python API per ADR-0007).

These were previously MCP tools in
``.olav/workspace/netops/analyze/tools/`` (R91 Step 3). They are now
plain Python functions called directly by the inspect_drift_* MCP tools.

Each function reads from the platform's main DuckDB and returns a
JSON-serialisable dict. Output lists are capped (50 rows for SQL
diff, 20 for routing/topology) to prevent agent context overflow.
"""

from .configs import diff_configs
from .routing_drift import diff_routing_drift
from .sql_state import diff_sql_state
from .topology_drift import diff_topology_drift

__all__ = [
    "diff_configs",
    "diff_routing_drift",
    "diff_sql_state",
    "diff_topology_drift",
]

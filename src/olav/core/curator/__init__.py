"""Curator helpers (Python API per ADR-0007).

These were previously MCP tools in
``.olav/workspace/audit/curator/tools/`` (R91 Step 4 fold). They
are now plain Python functions; the curator agent imports them
from skill scripts (per ADR-0008, R92.3).

Public entry points:
    * ``discover_view_schemas`` — LLM + DB schema mapping
    * ``fuzzy_map_schema`` — vendor → standard schema normalisation
    * ``sync_schema_reference`` — regenerate SCHEMA_REFERENCE.md
    * ``scaffold_domain_agent`` — create new agent workspace
    * ``trace_learner`` — review failures, extract constraints
"""

from .discover_view_schemas import discover_view_schemas
from .fuzzy_map_schema import fuzzy_map_schema
from .scaffold_domain_agent import scaffold_domain_agent
from .sync_schema_reference import sync_schema_reference
from .trace_learner import trace_learner

__all__ = [
    "discover_view_schemas",
    "fuzzy_map_schema",
    "scaffold_domain_agent",
    "sync_schema_reference",
    "trace_learner",
]

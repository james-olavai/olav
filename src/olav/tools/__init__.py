"""LangChain tools for network operations.

This module provides both:
1. LangChain @tool decorated functions (for LangGraph ToolNode)
2. BaseTool classes that register with ToolRegistry (for Strategies)

All *_tool.py modules are imported here to ensure ToolRegistry population
on package import. This is important for FastPathStrategy and DeepPathStrategy
which use ToolRegistry.get_tool() for schema discovery.
"""

# Import all tool modules to trigger ToolRegistry.register() side effects
from olav.tools import (
    datetime_tool,
    netbox_tool,
    nornir_tool,
    opensearch_tool,
    suzieq_tool,
)

# Note: suzieq_parquet_tool and cli_tool are LangChain @tool functions,
# not BaseTool classes, so they don't register with ToolRegistry.
# They are used directly by workflow ToolNodes.

__all__ = [
    "datetime_tool",
    "netbox_tool",
    "nornir_tool",
    "opensearch_tool",
    "suzieq_tool",
]

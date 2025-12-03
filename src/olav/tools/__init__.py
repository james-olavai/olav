"""LangChain tools for network operations.

This module provides both:
1. LangChain @tool decorated functions (for LangGraph ToolNode)
2. BaseTool classes that register with ToolRegistry (for Strategies)

Tool Organization:
- datetime_tool: Time utilities
- netbox_tool: NetBox API integration (NetBoxAPITool class)
- nornir_tool: NETCONF/CLI execution (NetconfTool, CLITool)
- opensearch_tool: Schema and document search
- suzieq_tool: BaseTool classes for ToolRegistry
- suzieq_parquet_tool: @tool functions for Parquet queries (direct import)
- indexing_tool: Document indexing utilities (direct import)

Usage:
    # For ToolRegistry-based access
    from olav.tools.base import ToolRegistry
    tool = ToolRegistry.get_tool("suzieq_query")

    # For LangGraph ToolNode (direct @tool functions)
    from olav.tools.suzieq_parquet_tool import suzieq_query, suzieq_schema_search
"""

# Import all tool modules to trigger ToolRegistry.register() side effects
from olav.tools import (
    datetime_tool,
    netbox_tool,
    nornir_tool,
    opensearch_tool,
    suzieq_tool,
)
from olav.tools.base import BaseTool, ToolRegistry

# Re-export commonly used classes
from olav.tools.netbox_tool import NetBoxAPITool

# Note: The following are @tool functions (not BaseTool classes):
# - suzieq_parquet_tool: suzieq_query, suzieq_schema_search
# - indexing_tool: index_document, index_directory, search_indexed_documents
# Import them directly when needed for LangGraph ToolNode.

__all__ = [
    "BaseTool",
    # Classes
    "NetBoxAPITool",
    "ToolRegistry",
    # Modules
    "datetime_tool",
    "netbox_tool",
    "nornir_tool",
    "opensearch_tool",
    "suzieq_tool",
]

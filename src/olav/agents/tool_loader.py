"""Dynamic Tool Loading for Specialist Sub-Agents.

This module implements the dynamic tool loading mechanism for specialist agents,
ensuring each agent only has access to relevant tools for its domain.

Roadmap: Task 10.2 - Specialist Sub-Agents with Built-in Guards
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Literal

from langchain_core.tools import BaseTool

from olav.tools.network import nornir_execute
from olav.tools.react_query import query_network
from olav.tools.sync_tools import sync_all

logger = logging.getLogger(__name__)

AgentType = Literal["detective", "coder", "analyzer", "general"]


def load_tools_for_agent(
    agent_type: AgentType,
    custom_tools: list[BaseTool] | None = None,
) -> list[Callable[..., Any] | BaseTool]:
    """Load tools for a specific agent type.

    This function implements the principle of least privilege, ensuring
    each specialist agent only has access to tools relevant to its domain.

    Args:
        agent_type: Type of specialist agent
        custom_tools: Optional additional tools to include

    Returns:
        List of tools available to the agent

    Examples:
        >>> detective_tools = load_tools_for_agent("detective")
        >>> coder_tools = load_tools_for_agent("coder")
    """
    tool_registry: dict[AgentType, list[Callable[..., Any] | BaseTool]] = {
        "detective": [
            # SQL/Graph query tools
            query_network,
        ],
        "coder": [
            # Code execution and generation tools
            # Note: Python sandbox execution will be added separately
        ],
        "analyzer": [
            # Network analysis tools
            nornir_execute,
            sync_all,
            # Database access for historical analysis
            query_network,
        ],
        "general": [
            # Full toolset for general-purpose agent
            query_network,
            nornir_execute,
            sync_all,
        ],
    }

    tools = tool_registry.get(agent_type, tool_registry["general"])

    # Add custom tools if provided
    if custom_tools:
        tools.extend(custom_tools)

    logger.info(f"Loaded {len(tools)} tools for agent type '{agent_type}'")

    return tools


def get_tool_whitelist(agent_type: AgentType) -> list[str]:
    """Get whitelist of allowed tool names for an agent type.

    This implements safety guardrails by explicitly listing which tools
    each agent type is allowed to use.

    Args:
        agent_type: Type of specialist agent

    Returns:
        List of allowed tool names

    Examples:
        >>> whitelist = get_tool_whitelist("detective")
        >>> "nornir_execute" in whitelist
        False
    """
    whitelists: dict[AgentType, list[str]] = {
        "detective": [
            "query_network",
            # Explicitly BLOCKED: execute_network_command (read-only access)
        ],
        "coder": [
            # Code generation tools only
            # Network execution is BLOCKED for coder agent
        ],
        "analyzer": [
            "query_network",
            "nornir_execute",
            "sync_all",
        ],
        "general": [
            "query_network",
            "nornir_execute",
            "sync_all",
        ],
    }

    return whitelists.get(agent_type, whitelists["general"])


def validate_tool_access(agent_type: AgentType, tool_name: str) -> bool:
    """Validate if an agent type is allowed to use a specific tool.

    Args:
        agent_type: Type of specialist agent
        tool_name: Name of the tool to validate

    Returns:
        True if tool is allowed, False otherwise

    Examples:
        >>> validate_tool_access("detective", "nornir_execute")
        False
        >>> validate_tool_access("detective", "query_database")
        True
    """
    whitelist = get_tool_whitelist(agent_type)
    is_allowed = tool_name in whitelist

    if not is_allowed:
        logger.warning(
            f"Agent '{agent_type}' blocked from using tool '{tool_name}' (not in whitelist)"
        )

    return is_allowed

"""OLAV Middleware - Auto-inject tool descriptions into prompts.

Middleware pattern inspired by deepagents architecture, implementing automatic
tool description injection, keeping base prompts concise (<20 lines) while
ensuring consistent tool usage patterns.

Usage:
    from olav.middleware import tool_middleware

    enriched_prompt = tool_middleware.enrich_prompt(
        base_prompt="You are a network diagnostics expert...",
        tools=[suzieq_query, netconf_tool]
    )
"""

from olav.middleware.tool_middleware import ToolMiddleware, tool_middleware

__all__ = ["ToolMiddleware", "tool_middleware"]

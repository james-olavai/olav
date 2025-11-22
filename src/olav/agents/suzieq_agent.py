"""SuzieQ SubAgent factory.

Provides a helper to construct the read-only SuzieQ analysis agent
based on the schema-aware tools.
"""
from deepagents import SubAgent

# Use Parquet-based Schema-Aware SuzieQ tools (avoids pydantic v1/v2 conflicts)
from olav.tools.suzieq_parquet_tool import suzieq_query, suzieq_schema_search
from olav.core.prompt_manager import prompt_manager


def create_suzieq_subagent() -> SubAgent:
    """Create the SuzieQ read-only SubAgent.

    Returns:
        Configured SubAgent for SuzieQ queries (read-only, no HITL needed).
    """
    suzieq_prompt = prompt_manager.load_agent_prompt("suzieq_agent")
    
    return SubAgent(
        name="suzieq-analyzer",
        description=(
            "查询和分析网络设备状态、接口信息、BGP/OSPF 邻居关系、路由表、"
            "ARP/NDP 表等网络数据（基于 SuzieQ 历史数据）。"
            "适用场景：设备接口统计、BGP 邻居状态、路由可达性分析、网络拓扑发现等。"
        ),
        system_prompt=suzieq_prompt,
        tools=[suzieq_schema_search, suzieq_query],
        # No interrupt_on - read-only operations
    )

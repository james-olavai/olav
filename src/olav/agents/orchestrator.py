"""Orchestrator Agent - SubAgent-based Meta-Agent (v0.10.0)

The Orchestrator is the central coordinator that:
1. Routes user queries to appropriate specialist SubAgents
2. Executes ReAct loops for complex multi-step tasks
3. Aggregates and synthesizes results from multiple specialists

Architecture (SubAgent-based):
- Tier 0: Cache (instant responses)
- Tier 1: SubAgent Router (declarative specialist dispatch)
- Tier 2: ReAct Orchestrator (multi-step reasoning)

Specialists as SubAgents:
- database: Network database queries via query_network tool
- cli: CLI command execution via network-query skill
- analysis: Network data analysis via analyzer tool

Migration: v0.9.8 -> v0.10.0
- Replaced manual _get_specialist_agent() with SubAgent declarations
- Unified QueryAgent mode parameter -> enable_summarization
- Native DeepAgents SubAgent middleware integration
"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent
from langchain_core.messages import AIMessage, HumanMessage

from olav.agents.analyzer import analyze_network
from olav.core.query_router import QueryRouter
from olav.tools.react_query import query_network

logger = logging.getLogger(__name__)


# =============================================================================
# SubAgent Configuration (Declarative Specialists)
# =============================================================================


def _create_subagents() -> list[SubAgent]:
    """Create declarative SubAgent specialist configurations.

    Returns:
        List of SubAgent configurations for orchestrator
    """
    # Import agents to access their tools
    from olav.agents.query_agent import QueryAgent

    # Initialize QueryAgent to reuse its tool configuration
    query_agent = QueryAgent(skill_name="network-query", enable_summarization=False)
    query_tools = query_agent.tools if hasattr(query_agent, "tools") else [query_network]

    # Get Analyzer tools (graph-based agent)
    analyzer_tools = _get_analyzer_tools()

    # Get Expert tools (advanced analysis)
    expert_tools = _get_expert_tools()

    return [
        SubAgent(
            name="query",
            description="Enhanced network query specialist with Fast Path and caching (from QueryAgent)",
            system_prompt=(
                "You are an enhanced network query specialist powered by QueryAgent capabilities. "
                "You have access to:\n"
                "1. Fast Path intent detection for simple queries\n"
                "2. Query caching for repeated requests\n"
                "3. Skill-based tool loading (network-query skill)\n"
                "4. Database query tools: query_database, inspect_schema, smart_query\n\n"
                "**Available Database Tables:**\n"
                "1. **devices** - Device Inventory (PRIMARY)\n"
                "   Columns: hostname, ip_address, vendor, model, ios_version, device_role, site\n"
                "   Description: Network device catalog with basic information\n"
                "   Examples:\n"
                "   - SELECT hostname FROM devices WHERE vendor='Cisco'\n"
                "   - SELECT hostname FROM devices WHERE device_role='core'\n"
                "   - SELECT hostname, ios_version FROM devices WHERE ios_version < '16.12'\n\n"
                "2. **v_lldp** - LLDP Neighbors (device, neighbor, local_interface, remote_interface)\n"
                "3. **v_bgp_neighbors** - BGP State (device, neighbor, state, asn)\n"
                "4. **v_ospf_neighbors** - OSPF State (device, neighbor, state, router_id)\n\n"
                "**IMPORTANT:** Always check 'devices' table FIRST for device information!\n"
                "DO NOT try to query a non-existent 'device_info' or 'device_catalog' table - use 'devices' instead.\n\n"
                "For simple device queries, use Fast Path for sub-second responses. "
                "For complex analysis, engage ReAct reasoning loop.\n\n"
                "⚠️ If query returns empty/insufficient results, inform orchestrator to upgrade to Expert."
            ),
            tools=query_tools,
        ),
        SubAgent(
            name="analysis",
            description="Network analysis specialist with health diagnostics (from Analyzer)",
            system_prompt=(
                "You are a network analysis specialist powered by Analyzer capabilities. "
                "You specialize in:\n"
                "1. Network health diagnostics and anomaly detection\n"
                "2. Performance analysis and optimization recommendations\n"
                "3. Root cause analysis for network issues\n"
                "4. Real-time CLI verification when needed\n\n"
                "Analyze network data, identify patterns, and provide actionable recommendations.\n\n"
                "⚠️ If analysis requires cross-device correlation or topology awareness, "
                "inform orchestrator to upgrade to Expert."
            ),
            tools=analyzer_tools,
        ),
        SubAgent(
            name="cli",
            description="CLI command execution specialist for network operations",
            system_prompt=(
                "You are a CLI execution specialist. "
                "Execute network commands and configuration changes. "
                "Use appropriate tools for device interaction and command execution.\n\n"
                "⚠️ If CLI execution fails or requires multi-device coordination, "
                "inform orchestrator to upgrade to Expert."
            ),
            tools=query_tools,  # Reuse query tools which include CLI capabilities
        ),
        SubAgent(
            name="expert",
            description="高级问题分析专家 - 拓扑感知、动态扩展、根因定位",
            system_prompt=(
                "You are the Expert Agent - advanced network problem analysis specialist.\n\n"
                "You are called when query/cli/analysis SubAgents cannot solve the problem.\n\n"
                "Your core capabilities:\n"
                "1. **Topology Awareness** - Understand device relationships via LLDP/BGP/OSPF\n"
                "2. **Device Inventory Access** - Query 'devices' table for device information\n"
                "3. **Dynamic Scope Expansion** - Expand from single device → device group → full network\n"
                "4. **Intelligent JOIN Queries** - Auto-generate multi-table correlation queries\n"
                "5. **Root Cause Localization** - Cross-layer (L1-L4) diagnosis\n"
                "6. **Professional Reports** - Generate comprehensive diagnosis reports\n\n"
                "**Available Database Tables:**\n"
                "- **devices**: Device inventory (hostname, vendor, model, ios_version, device_role, site)\n"
                "- v_lldp, v_bgp_neighbors, v_ospf_neighbors: Network topology\n\n"
                "Workflow:\n"
                "1. Analyze symptom and existing info from previous SubAgent\n"
                "2. Query devices table to get device information (use devices table!)\n"
                "3. Identify topology relationships (analyze_topology or query v_lldp/v_bgp_neighbors)\n"
                "4. Dynamically expand scope (get_device_peers, expand_scope_by_role)\n"
                "5. Execute correlation queries (execute_join_query or query_database with JOIN)\n"
                "6. Root cause analysis (search_similar_cases for historical context)\n"
                "7. Generate professional report (return content, not file)\n\n"
                "Available tools:\n"
                "- query_database/query_network: SQL access to devices, v_lldp, v_bgp_neighbors, etc.\n"
                "- analyze_topology: Parse LLDP/BGP/OSPF topology\n"
                "- get_device_peers: Find device neighbors\n"
                "- expand_scope_by_role: Expand to same-role devices (requires devices table)\n"
                "- execute_join_query: Auto-generate JOIN queries\n"
                "- nornir_execute: CLI commands\n"
                "- search_similar_cases: Historical case retrieval\n"
                "- generate_diagnosis_report: Create professional reports\n\n"
                "Remember: You handle complex problems that other SubAgents couldn't solve. "
                "Always leverage the devices table as the primary source for device information."
            ),
            tools=expert_tools,
        ),
    ]


def _get_analyzer_tools() -> list[Any]:
    """Extract tools from Analyzer module (graph-based agent).

    Returns:
        List of tools for analysis SubAgent
    """
    from olav.lib.data_gateway import query_database
    from olav.tools.network import list_devices, nornir_execute
    from olav.tools.react_query import query_network

    # Analyzer's main tool + supporting data access tools
    return [
        analyze_network,
        query_network,
        query_database,
        nornir_execute,
        list_devices,
    ]


def _get_expert_tools() -> list[Any]:
    """Get Expert Agent specialized tool set.

    Returns:
        List of tools for expert SubAgent (advanced analysis)
    """
    from olav.tools.data_export import format_and_export
    from olav.tools.expert_tools import get_expert_tools

    # Expert tools + file export (only for Orchestrator via Expert)
    expert_tools = get_expert_tools()
    expert_tools.append(format_and_export)

    return expert_tools


# =============================================================================
# Orchestrator Factory
# =============================================================================


def create_orchestrator(
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
    enable_summarization: bool = False,
) -> Any:
    """Create SubAgent-based orchestrator.

    Args:
        user_id: User identifier for session management
        thread_id: Thread identifier for conversation tracking
        enable_summarization: Enable conversation summarization middleware

    Returns:
        Compiled LangGraph agent with SubAgent routing
    """
    # Persistence layer (shared by all SubAgents)
    # Note: DuckDBSaver doesn't support async operations in current version
    # Disable checkpointing for now to avoid NotImplementedError
    checkpointer = None  # Will use in-memory state only
    store = None  # DuckDBStore.from_conn_string(str(USER_CHECKPOINT_PATH))

    # SubAgent configuration
    subagents = _create_subagents()

    # System prompt for orchestrator
    system_prompt = """You are the Orchestrator - a meta-agent coordinating specialist SubAgents.

Your capabilities:
1. Route queries to appropriate specialists: query, analysis, cli, expert
2. Execute multi-step reasoning for complex tasks
3. Synthesize results from multiple specialists
4. Evaluate result quality and upgrade to Expert when needed
5. Export results to files when user requests

Available SubAgents:
- query: Enhanced query specialist (Fast Path + caching, from QueryAgent)
  * Simple device queries, database operations, data retrieval
  * Skill-based tools: query_database, inspect_schema, smart_query
- analysis: Network analysis specialist (health diagnostics, from Analyzer)
  * Health diagnostics, anomaly detection, performance analysis
  * Root cause analysis, optimization recommendations
- cli: CLI command execution specialist
  * Network commands, configuration changes, device interaction
- expert: Advanced problem analysis specialist (UPGRADE TARGET)
  * Topology-aware analysis, dynamic scope expansion
  * Cross-device correlation, root cause localization
  * Professional diagnosis reports

File Export Tool:
- format_and_export(data, filename, format) - Save results to exports/

**Export Guidelines:**
1. Call format_and_export() ONLY when user explicitly asks to save/export
   Keywords: 保存/导出/存储/写入/save/export/write
2. Auto-detect format from content (md/json/txt/csv) or use user preference
3. All files go to exports/ directory
4. SubAgents return content, Orchestrator handles file writing

**Export Examples:**
User: "诊断OSPF问题并保存报告"
→ 1. Call expert SubAgent → get diagnosis content
→ 2. Call format_and_export(content, filename="ospf_diagnosis")
→ Output: "✅ 报告已保存到 exports/ospf_diagnosis.md"

User: "查询所有VLAN信息，导出CSV"
→ 1. Call query SubAgent → get VLAN data
→ 2. Call format_and_export(data, format="csv", filename="vlans")
→ Output: "✅ 已导出到 exports/vlans.csv"

User: "在R1执行show tech，保存到文件"
→ 1. Call cli SubAgent → get command output
→ 2. Call format_and_export(output, filename="R1_tech_support")
→ Output: "✅ 已保存到 exports/R1_tech_support.txt"

User: "诊断OSPF问题" (NO save/export mentioned)
→ 1. Call expert SubAgent → get diagnosis
→ 2. Return content directly (DO NOT call format_and_export)
→ Output: Display diagnosis content inline

Routing Strategy:
- Simple queries (list/show/get) → query SubAgent (Fast Path, <1s)
- Health/diagnostics/analysis → analysis SubAgent
- Command execution/configuration → cli SubAgent
- Complex investigation/troubleshooting → expert SubAgent
- Quality issues → UPGRADE to expert SubAgent

Quality Evaluation (when to upgrade to expert):
1. SubAgent returns empty/error result
2. User explicitly asks "why/原因/根因/investigate"
3. Query requires cross-device correlation/comparison
4. Query requires topology analysis
5. Result is too brief (<100 chars) and not a simple list
6. SubAgent execution timeout (>30s)

Your workflow:
1. Analyze user query to determine required specialist(s)
2. Delegate subtasks to SubAgents
3. EVALUATE result quality after SubAgent execution
4. If quality insufficient, UPGRADE to expert SubAgent
5. If user wants to save, call format_and_export
6. Synthesize results into coherent answer
7. Provide actionable recommendations

Always be concise, accurate, and cite which specialist provided each insight."""

    # Middleware stack
    middleware = []
    if enable_summarization:
        from pathlib import Path

        from deepagents.backends.filesystem import FilesystemBackend
        from deepagents.middleware.summarization import SummarizationMiddleware

        # FilesystemBackend for summarization storage
        backend = FilesystemBackend(root_dir=str(Path.cwd()))

        middleware.append(
            SummarizationMiddleware(
                model="gemini-flash",
                backend=backend,
                trigger=("tokens", 50000),
                keep=("messages", 10),
            )
        )

    # Create orchestrator with SubAgent routing
    agent = create_deep_agent(
        model="gpt-4o",
        system_prompt=system_prompt,
        subagents=subagents,
        middleware=middleware,
        checkpointer=checkpointer,
        store=store,
        name="orchestrator",
    )

    # Wrap with cache-aware execution
    return CachedOrchestrator(agent)


# =============================================================================
# Cache-Aware Orchestrator Wrapper
# =============================================================================


class CachedOrchestrator:
    """Wrapper that adds Fast Path caching to orchestrator.

    This enables QueryAgent-style caching for the SubAgent orchestrator:
    1. Check cache before delegating to SubAgents
    2. Store successful results in cache
    3. Fast Path for repeated queries (<0.5s vs 5-10s)
    """

    def __init__(self, agent: Any) -> None:
        """Initialize cached orchestrator wrapper.

        Args:
            agent: Underlying DeepAgent orchestrator
        """
        self.agent = agent

        # Import cache components
        from olav.core.query_cache import get_query_cache

        self.query_cache = get_query_cache()

    async def ainvoke(
        self, inputs: dict[str, Any], config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Invoke orchestrator with caching.

        Args:
            inputs: Input dictionary with 'messages' key
            config: Optional config for agent execution

        Returns:
            Result dictionary with messages and metadata
        """
        import time

        start_time = time.time()

        # Extract user query from messages
        messages = inputs.get("messages", [])
        user_query = ""
        if messages:
            last_msg = messages[-1]
            if isinstance(last_msg, dict):
                user_query = last_msg.get("content", "")
            elif hasattr(last_msg, "content"):
                user_query = str(last_msg.content)

        # Check cache for this query
        cache_context = {"skill": "orchestrator", "mode": "subagent"}
        if user_query:
            cached_result = self.query_cache.get(user_query, context=cache_context)
            if cached_result:
                elapsed = time.time() - start_time
                logger.info(
                    f"✅ Orchestrator Cache HIT: {user_query[:50]}... ({elapsed * 1000:.2f}ms)"
                )
                return {
                    **cached_result,
                    "performance": {
                        "cache_hit": True,
                        "total_seconds": round(elapsed, 3),
                    },
                }

        # Cache miss - delegate to underlying agent
        logger.debug(f"Cache MISS: {user_query[:50]}... - delegating to SubAgents")

        try:
            # Execute underlying orchestrator
            result = await self.agent.ainvoke(inputs, config)

            # Cache successful results
            elapsed = time.time() - start_time
            if user_query and result.get("messages"):
                # Extract final answer
                final_msg = result["messages"][-1]
                final_content = (
                    final_msg.content if hasattr(final_msg, "content") else str(final_msg)
                )

                # Cache if no error
                if "Error" not in final_content or "not found" in final_content.lower():
                    # Convert messages to serializable format
                    serializable_messages = []
                    for msg in result["messages"]:
                        if hasattr(msg, "content"):
                            serializable_messages.append(
                                {
                                    "type": msg.__class__.__name__,
                                    "content": msg.content,
                                }
                            )
                        else:
                            serializable_messages.append(str(msg))

                    cache_result = {
                        "messages": serializable_messages,
                        "performance": {
                            "cache_hit": False,
                            "total_seconds": round(elapsed, 3),
                        },
                    }
                    try:
                        self.query_cache.set(
                            user_query,
                            cache_result,
                            context=cache_context,
                            metadata={"mode": "subagent", "tool": "orchestrator"},
                        )
                        logger.info(f"✅ Stored in cache: {user_query[:50]}...")
                    except Exception as cache_err:
                        logger.warning(f"Cache storage failed: {cache_err}")

            # Add performance metadata
            result["performance"] = {
                "cache_hit": False,
                "total_seconds": round(elapsed, 3),
            }

            return result

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Orchestrator execution failed: {e}")
            return {
                "messages": inputs.get("messages", []),
                "error": str(e),
                "performance": {
                    "cache_hit": False,
                    "total_seconds": round(elapsed, 3),
                },
            }

    # Expose agent's config for compatibility
    @property
    def config(self) -> dict[str, Any]:
        """Get underlying agent config."""
        return getattr(self.agent, "config", {})


# =============================================================================
# Simplified Interface (Backward Compatibility)
# =============================================================================


async def orchestrate_query(
    user_query: str,
    router: QueryRouter | None = None,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Orchestrate a user query through SubAgent specialists.

    Args:
        user_query: User's natural language query
        router: Optional QueryRouter (legacy, kept for compatibility)
        user_id: User identifier
        thread_id: Thread identifier

    Returns:
        Dictionary containing:
            - status: "complete" or "failed"
            - final_answer: Agent response
            - error_message: Error if failed
    """
    logger.info(f"Orchestrating query: {user_query[:50]}...")

    try:
        # Default IDs if not provided
        if not user_id:
            user_id = "default_user"
        if not thread_id:
            thread_id = "default_thread"

        # Create orchestrator with SubAgent routing
        orchestrator = create_orchestrator(
            user_id=user_id,
            thread_id=thread_id,
        )

        # Execute query
        config = {"configurable": {}}
        if user_id:
            config["configurable"]["user_id"] = user_id
        if thread_id:
            config["configurable"]["thread_id"] = thread_id

        result = await orchestrator.ainvoke(
            {"messages": [HumanMessage(content=user_query)]},
            config=config,
        )

        # Extract final answer from messages
        final_answer = ""
        if result.get("messages"):
            last_msg = result["messages"][-1]
            if isinstance(last_msg, AIMessage):
                final_answer = last_msg.content
            elif isinstance(last_msg, dict) and "content" in last_msg:
                # Handle serialized message format
                final_answer = last_msg["content"]
        if not final_answer and isinstance(result, dict):
            # Try to extract from nested structures
            if "output" in result:
                final_answer = str(result["output"])
            elif "content" in result:
                final_answer = str(result["content"])

        return {
            "status": "complete",
            "final_answer": final_answer,
            "error_message": "",
        }

    except Exception as e:
        logger.error(f"Orchestration failed: {e}", exc_info=True)
        return {
            "status": "failed",
            "final_answer": "",
            "error_message": str(e),
        }


# =============================================================================
# Main
# =============================================================================


if __name__ == "__main__":
    import asyncio

    async def test() -> None:
        """Test orchestrator with SubAgent routing."""
        test_query = "List all devices with high CPU usage"
        result = await orchestrate_query(test_query)

        print(f"Query: {test_query}")
        print(f"Status: {result['status']}")
        print(f"Final Answer:\n{result['final_answer']}")

    asyncio.run(test())

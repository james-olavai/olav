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
from typing import Any, Sequence

from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent, CompiledSubAgent
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
    # Import direct database tools (NO agent creation - Fix for query routing failure)
    from olav.tools.react_query import (
        query_database,    # Direct SQL access
        inspect_schema,    # Schema inspection  
        discover_data,     # File discovery
    )
    
    # Database tools for query SubAgent
    database_tools = [
        query_database,
        inspect_schema,
        discover_data,
    ]

    # Get Analyzer tools (graph-based agent)
    analyzer_tools = _get_analyzer_tools()

    # Get Expert tools (advanced analysis)
    expert_tools = _get_expert_tools()

    return [
        SubAgent(
            name="query",
            description="Database query specialist with direct SQL access",
            system_prompt=(
                "You are a database query specialist with direct SQL access to network database.\n\n"
                "**Available Tools:**\n"
                "1. query_database(sql, params) - Execute SQL on .olav/db/main.duckdb\n"
                "2. inspect_schema(table_name) - Check available tables and columns\n"
                "3. discover_data(pattern) - Find parsed data files in exports/\n\n"
                "**Available Database Tables:**\n"
                "1. **devices** - Device Inventory (PRIMARY) - GUARANTEED TO EXIST\n"
                "   Columns: hostname, ip_address, vendor, model, ios_version, device_role, site\n"
                "   Database: .olav/db/main.duckdb\n"
                "   Description: Network device catalog with basic information\n"
                "   Examples:\n"
                "   - query_database(\"SELECT hostname, ip_address FROM devices WHERE hostname='R2'\")\n"
                "   - query_database(\"SELECT hostname FROM devices WHERE vendor='Cisco'\")\n"
                "   - query_database(\"SELECT hostname, ios_version FROM devices WHERE ios_version < '16.12'\")\n\n"
                "2. **raw_outputs** - CLI Command Outputs (device, command, output, timestamp)\n"
                "   Use for accessing raw CLI output data\n\n"
                "3. **Other tables** - Use inspect_schema() to discover (v_lldp, v_bgp_neighbors may exist)\n\n"
                "**Workflow:**\n"
                "1. If unsure about schema, call inspect_schema() or inspect_schema('table_name')\n"
                "2. Execute SQL query with query_database(sql)\n"
                "3. If table doesn't exist, inform orchestrator (don't try to create it)\n"
                "4. Return query results as JSON to orchestrator\n"
                "5. Let orchestrator handle file exports - YOU only retrieve data\n\n"
                "**Critical Rules:**\n"
                "- ALWAYS use 'devices' table for device inventory (hostname, IP, vendor, etc.)\n"
                "- For interface data: Return what exists in DB, or inform 'data not in database'\n"
                "- DO NOT create agents or call complex workflows\n"
                "- DO NOT attempt to export files - that's orchestrator's job\n"
                "- If query returns empty, suggest checking with inspect_schema()\n\n"
                "⚠️ YOU are responsible for data retrieval ONLY. "
                "Return results, don't try to process or export them."
            ),
            tools=database_tools,  # Direct DB tools, NO agent recursion
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
            tools=database_tools,  # Reuse database tools for now (CLI tools TBD)
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
                "- **devices**: Device inventory (hostname, ip_address, vendor, model, ios_version, device_role, site)\n"
                "- **raw_outputs**: CLI command outputs (device, command, output, timestamp)\n"
                "- Check for topology views (v_lldp, v_bgp_neighbors, v_ospf_neighbors) before using\n\n"
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
    from olav.tools.network import list_devices, nornir_execute
    from olav.tools.react_query import query_database, query_network

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
    # Import orchestrator's own tools (separate from SubAgent tools)
    from olav.tools.data_export import format_and_export
    
    # Orchestrator's own tools for file export
    orchestrator_tools = [
        format_and_export,  # File export capability
    ]
    
    # Persistence layer (skill-level checkpoint - v0.10.0+)
    # Each skill has its own isolated checkpoint database
    from langgraph.checkpoint.duckdb import DuckDBSaver
    from langgraph.store.duckdb import DuckDBStore
    from config.paths import ORCHESTRATOR_CHECKPOINT_PATH
    
    ORCHESTRATOR_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        checkpointer = DuckDBSaver.from_conn_string(str(ORCHESTRATOR_CHECKPOINT_PATH)).__enter__()
        store = DuckDBStore.from_conn_string(str(ORCHESTRATOR_CHECKPOINT_PATH)).__enter__()
        logger.info(f"Orchestrator checkpoint enabled: {ORCHESTRATOR_CHECKPOINT_PATH}")
    except Exception as e:
        logger.warning(f"Failed to initialize Orchestrator checkpoint: {e}")
        checkpointer = None
        store = None

    # SubAgent configuration
    subagents = _create_subagents()

    # Load system prompt from SKILL.md (v0.10.0+ Skill-Centric Architecture)
    from olav.core.skill_loader import get_skill_loader
    
    loader = get_skill_loader()
    orchestrator_skill = loader.get_skill("orchestrator")
    
    if orchestrator_skill and orchestrator_skill.content:
        # Extract system prompt from markdown content (after frontmatter)
        content_lines = orchestrator_skill.content.split('\n')
        
        # Find where frontmatter ends (second '---')
        fm_end = 0
        count = 0
        for i, line in enumerate(content_lines):
            if line.strip() == '---':
                count += 1
                if count == 2:
                    fm_end = i + 1
                    break
        
        # Use markdown content as system prompt (everything after frontmatter)
        system_prompt = '\n'.join(content_lines[fm_end:]).strip()
        logger.info(f"Loaded Orchestrator system prompt from {orchestrator_skill.file_path} ({len(system_prompt)} chars)")
    else:
        raise ValueError(
            "Orchestrator SKILL.md not found or empty at .olav/skills/orchestrator/SKILL.md. "
            "This file is required for Skill-Centric Architecture."
        )

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
        tools=orchestrator_tools,  # Orchestrator's own tools (format_and_export)
        subagents=tuple(subagents) if subagents else None,  # Convert list to Sequence (tuple)
        middleware=tuple(middleware) if middleware else (),  # Convert list to Sequence (tuple)
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

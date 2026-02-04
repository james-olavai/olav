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
    # Import QueryAgent to access its tools
    from olav.agents.query_agent import QueryAgent
    
    # Initialize QueryAgent to reuse its tool configuration
    # Use minimal setup to just get the tools
    query_agent = QueryAgent(skill_name="network-query", enable_summarization=False)
    
    # Get tools from QueryAgent (stored in query_agent.tools)
    query_tools = query_agent.tools if hasattr(query_agent, 'tools') else [query_network]
    
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
                "For simple device queries, use Fast Path for sub-second responses. "
                "For complex analysis, engage ReAct reasoning loop."
            ),
            tools=query_tools,
        ),
        SubAgent(
            name="database",
            description="Network database specialist for querying device data",
            system_prompt=(
                "You are a network database specialist. "
                "Use the query_network tool to answer questions about network devices, "
                "interfaces, configurations, and performance metrics."
            ),
            tools=[query_network],
        ),
        SubAgent(
            name="cli",
            description="CLI command execution specialist for network operations",
            system_prompt=(
                "You are a CLI execution specialist. "
                "You have access to network-query skill with tools including: "
                "query_database, inspect_schema, smart_query, and CLI commands. "
                "Use these tools to execute network operations."
            ),
            tools=[query_network],  # Will be augmented by SkillsMiddleware if needed
        ),
        SubAgent(
            name="analysis",
            description="Network data analysis specialist",
            system_prompt=(
                "You are a network analysis specialist. "
                "Use the analyze_network tool to perform advanced analytics, "
                "identify patterns, and provide actionable insights."
            ),
            tools=[analyze_network],
        ),
    ]


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
1. Route queries to appropriate specialists: query, database, cli, analysis
2. Execute multi-step reasoning for complex tasks
3. Synthesize results from multiple specialists

Available SubAgents:
- query: Enhanced query specialist (Fast Path + caching, from QueryAgent)
- database: Query network device data
- cli: Execute CLI commands
- analysis: Perform advanced analytics

Routing Strategy:
- Simple device queries → query SubAgent (Fast Path, <1s)
- Direct database operations → database SubAgent
- CLI commands → cli SubAgent
- Network analysis → analysis SubAgent

Your workflow:
1. Analyze user query to determine required specialist(s)
2. Delegate subtasks to SubAgents
3. Synthesize results into coherent answer
4. Provide actionable recommendations

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
        
    async def ainvoke(self, inputs: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
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
                logger.info(f"✅ Orchestrator Cache HIT: {user_query[:50]}... ({elapsed * 1000:.2f}ms)")
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
                final_content = final_msg.content if hasattr(final_msg, "content") else str(final_msg)
                
                # Cache if no error
                if "Error" not in final_content or "not found" in final_content.lower():
                    cache_result = {
                        "messages": result["messages"],
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

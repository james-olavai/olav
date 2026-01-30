"""Analyzer Agent - Network Analysis Specialist.

This specialist agent is dedicated to analyzing network health, diagnosing
issues, and providing actionable recommendations. It combines DB queries
with real-time CLI verification for accurate analysis.

Roadmap: Task 10.2 - Specialist Sub-Agents (Analyzer)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)


# =============================================================================
# State Definition
# =============================================================================


@dataclass
class AnalyzerState:
    """State for the Analyzer Agent.

    Attributes:
        user_query: User's query or problem description
        db_data: Data from DuckDB queries
        cli_data: Data from real-time CLI commands
        analysis: Combined analysis
        recommendations: Actionable recommendations
        status: Current status
        error_message: Error message if failed
    """

    user_query: str = ""
    db_data: dict[str, Any] = field(default_factory=dict)
    cli_data: dict[str, Any] = field(default_factory=dict)
    analysis: str = ""
    recommendations: list[str] = field(default_factory=list)
    status: str = "pending"  # pending, db_query, cli_verify, analyzing, complete, failed
    error_message: str = ""
    routing_decision: str = ""  # "static_only" or "verify_realtime"


# =============================================================================
# Agent Nodes
# =============================================================================


def create_llm() -> ChatOpenAI:
    """Create LLM instance for analyzer agent."""
    from olav.core.llm_interface import MapReduceLLM

    # Use standard settings via MapReduceLLM
    mr = MapReduceLLM(provider="openai")
    return mr.llm


def _should_verify_realtime(user_query: str, db_data: dict[str, Any]) -> bool:
    """Determine if real-time CLI verification is needed.

    Args:
        user_query: User's query
        db_data: Data from DB queries

    Returns:
        True if CLI verification is needed
    """
    query_lower = user_query.lower()

    # Priority 1: User explicitly asks for real-time
    if any(k in query_lower for k in ["current", "live", "now", "verify", "check status", "up to date"]):
        return True

    # Priority 2: Simple listing queries should NOT trigger real-time verification
    # unless there is a confirmed anomaly or staleness.
    if any(k in query_lower for k in ["list", "show", "what are", "display"]):
        return False

    # Also check if DB data is stale or indicates potential issues
    if db_data.get("is_stale", False) or db_data.get("has_anomaly", False):
        return True

    return False


async def db_query_node(state: AnalyzerState) -> AnalyzerState:
    """Query DuckDB for relevant network data.

    Args:
        state: Current agent state

    Returns:
        Updated state with DB data
    """
    logger.info("Querying DuckDB for network data")

    state.status = "db_query"

    try:
        import json

        from olav.tools.react_query import query_network

        # Phase 15: Use .invoke() and handle JSON response correctly
        # Note: query_network expects 'sql' arg and returns JSON string
        result_json = query_network.invoke({"sql": state.user_query})

        try:
            result_data = json.loads(result_json)
        except json.JSONDecodeError:
            result_data = {"error": f"Invalid JSON response: {result_json[:100]}", "data": []}

        if isinstance(result_data, dict) and "error" in result_data:
            logger.warning(f"DB query warning: {result_data['error']}")
            state.db_data = {"error": result_data["error"], "data": []}
        else:
            # query_network returns a list of rows on success
            rows = result_data if isinstance(result_data, list) else []
            state.db_data = {
                "data": rows,
                "sql": state.user_query,  # Best effort sql tracking
                "row_count": len(rows),
            }

        # Determine if real-time verification is needed
        needs_realtime = _should_verify_realtime(state.user_query, state.db_data)
        state.routing_decision = "verify_realtime" if needs_realtime else "static_only"

        state.status = "cli_verify" if needs_realtime else "analyzing"

        logger.info(f"DB query complete, routing: {state.routing_decision}")

    except Exception as e:
        state.error_message = f"DB query failed: {e}"
        state.status = "failed"
        logger.error(state.error_message)

    return state


async def cli_verify_node(state: AnalyzerState) -> AnalyzerState:
    """Verify current state using CLI commands.

    Args:
        state: Current agent state

    Returns:
        Updated state with CLI data
    """
    logger.info("Verifying with real-time CLI commands")

    state.status = "cli_verify"

    try:
        from olav.tools.network import nornir_execute

        # Determine which commands to run based on the query
        # For now, use a simple heuristic
        if "interface" in state.user_query.lower():
            command = "show interface"
        elif "bgp" in state.user_query.lower():
            command = "show ip bgp summary"
        elif "route" in state.user_query.lower():
            command = "show ip route"
        else:
            command = "show version"

        # Execute command (note: this would need device targeting in real usage)
        result = await nornir_execute(
            command=command,
            device_filter=None,  # All devices
        )

        state.cli_data = {
            "command": command,
            "output": result,
        }

        state.status = "analyzing"

        logger.info("CLI verification complete")

    except Exception as e:
        logger.warning(f"CLI verification failed: {e}")
        state.cli_data = {"error": str(e)}
        # Don't fail, continue with analysis using DB data
        state.status = "analyzing"

    return state


async def analyze_node(state: AnalyzerState) -> AnalyzerState:
    """Analyze DB and CLI data to provide insights.

    Args:
        state: Current agent state

    Returns:
        Updated state with analysis and recommendations
    """
    logger.info("Analyzing data and generating recommendations")

    state.status = "analyzing"

    try:
        llm = create_llm()
        prompt = _build_analysis_prompt(state)

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=state.user_query),
        ]

        response = await llm.ainvoke(messages)

        analysis = response.content if isinstance(response.content, str) else str(response.content)

        # Parse analysis and recommendations
        state.analysis = analysis
        state.recommendations = _extract_recommendations(analysis)

        state.status = "complete"

        logger.info("Analysis completed successfully")

    except Exception as e:
        state.error_message = f"Analysis failed: {e}"
        state.status = "failed"
        logger.error(state.error_message)

    return state


# =============================================================================
# Helper Functions
# =============================================================================


def _build_analysis_prompt(state: AnalyzerState) -> str:
    """Build prompt for analysis.

    Args:
        state: Current agent state

    Returns:
        Analysis prompt
    """
    prompt_parts = [
        "You are a Network Analysis Specialist providing expert insights.",
        "",
        "Data Sources:",
    ]

    # Add DB data
    if state.db_data.get("data"):
        prompt_parts.append(f"1. DuckDB Query Results ({state.db_data['row_count']} rows):")
        for row in state.db_data["data"][:5]:
            prompt_parts.append(f"   - {row}")
        if state.db_data["row_count"] > 5:
            prompt_parts.append(f"   ... and {state.db_data['row_count'] - 5} more rows")
    else:
        prompt_parts.append("1. No DB data available")

    # Add CLI data
    if state.cli_data.get("output"):
        prompt_parts.append("\n2. Real-time CLI Verification:")
        prompt_parts.append(f"   Command: {state.cli_data['command']}")
        prompt_parts.append(f"   Output: {state.cli_data['output'][:200]}...")
    elif state.cli_data.get("error"):
        prompt_parts.append(f"\n2. CLI verification failed: {state.cli_data['error']}")
    else:
        prompt_parts.append("\n2. No CLI verification performed (static analysis only)")

    prompt_parts.extend(
        [
            "",
            "Your task:",
            "1. Analyze the data sources above",
            "2. Identify key findings and patterns",
            "3. Detect any anomalies or issues",
            "4. Provide actionable recommendations",
            "",
            "Format your response as:",
            "## Analysis",
            "[Your analysis here]",
            "",
            "## Recommendations",
            "- [Recommendation 1]",
            "- [Recommendation 2]",
            "...",
        ]
    )

    return "\n".join(prompt_parts)


def _extract_recommendations(analysis: str) -> list[str]:
    """Extract recommendation bullets from analysis.

    Args:
        analysis: Analysis text

    Returns:
        List of recommendations
    """
    recommendations = []

    in_recommendations = False
    for line in analysis.split("\n"):
        line = line.strip()

        if "## Recommendations" in line:
            in_recommendations = True
            continue

        if in_recommendations and line.startswith("-"):
            recommendations.append(line[1:].strip())

    return recommendations


# =============================================================================
# Graph Creation
# =============================================================================


def create_analyzer_graph() -> StateGraph:
    """Create the Analyzer Agent graph.

    Returns:
        LangGraph StateGraph
    """
    workflow = StateGraph(AnalyzerState)

    # Add nodes
    workflow.add_node("db_query", db_query_node)
    workflow.add_node("cli_verify", cli_verify_node)
    workflow.add_node("analyze", analyze_node)

    # Add edges
    workflow.set_entry_point("db_query")

    # Conditional routing from db_query
    workflow.add_conditional_edges(
        "db_query",
        lambda s: s.status,
        {
            "cli_verify": "cli_verify",
            "analyzing": "analyze",
            "failed": END,
        },
    )

    workflow.add_edge("cli_verify", "analyze")
    workflow.add_edge("analyze", END)

    return workflow.compile()


@tool
async def analyze_network(
    user_query: str,
) -> str:
    """Analyze network using Analyzer Agent with Data Fusion logic.

    Implements:
    1. Static First: Always query DuckDB snapshot first (Instant, 60% confidence)
    2. Real-time Verify: If DB data indicates anomaly OR is stale, trigger CLI
    3. Fusion: Merge DB context with CLI reality

    Args:
        user_query: User's query or problem description
        model: LLM model name

    Returns:
        Analysis results with recommendations
    """
    logger.info(f"Analyzer processing query: {user_query}")

    try:
        # Create graph
        app = create_analyzer_graph()

        # Initial state
        initial_state = AnalyzerState(user_query=user_query)

        # Execute graph
        result = await app.ainvoke(initial_state)

        if result["status"] == "complete":
            output = [
                f"## Analysis\n{result.get('analysis', '')}",
                "\n## Recommendations",
            ]
            for rec in result.get("recommendations", []):
                output.append(f"- {rec}")

            return "\n".join(output)
        else:
            return f"❌ Analysis failed: {result.get('error_message', 'Unknown error')}"

    except Exception as e:
        logger.error(f"Analyzer failed: {e}")
        return f"❌ Analyzer Error: {e}"


# =============================================================================
# CLI Integration
# =============================================================================


def create_analyzer_agent(model: str = "gpt-4o") -> Callable[[str], str]:
    """Create a simple wrapper for backward compatibility.

    Args:
        model: LLM model name

    Returns:
        Callable agent
    """
    import asyncio

    def agent(user_input: str) -> str:
        """Analyze network using Analyzer Agent."""
        result = asyncio.run(analyze_network(user_input, model))

        if result["status"] == "success":
            path_icon = "⚡" if result["routing_decision"] == "static_only" else "🔍"
            output = [
                f"{path_icon} Analysis complete (routing: {result['routing_decision']})",
                "",
                result["analysis"],
            ]

            if result.get("recommendations"):
                output.extend(
                    [
                        "",
                        "## Recommendations:",
                    ]
                )
                for rec in result["recommendations"]:
                    output.append(f"  {rec}")

            return "\n".join(output)
        else:
            return f"❌ Analysis failed: {result.get('error', 'Unknown error')}"

    return agent


# =============================================================================
# Main
# =============================================================================


if __name__ == "__main__":
    import asyncio

    async def test() -> None:
        # Test query
        test_query = "Why is the network slow?"
        result = await analyze_network(test_query)

        print(f"Query: {test_query}")
        print(f"Status: {result['status']}")
        print(f"Result: {result}")

    asyncio.run(test())

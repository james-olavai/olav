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

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph

from config.settings import settings
from olav.lib.data_gateway import get_gateway

logger = logging.getLogger(__name__)

# Initialize DataGateway for learning
_gw = get_gateway()


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
        similar_cases: Similar historical cases for reference
    """

    user_query: str = ""
    db_data: dict[str, Any] = field(default_factory=dict)
    cli_data: dict[str, Any] = field(default_factory=dict)
    analysis: str = ""
    recommendations: list[str] = field(default_factory=list)
    status: str = "pending"  # pending, db_query, cli_verify, analyzing, complete, failed
    error_message: str = ""
    routing_decision: str = ""  # "static_only" or "verify_realtime"
    similar_cases: list[dict[str, Any]] = field(default_factory=list)  # Similar historical cases


# =============================================================================
# Agent Nodes
# =============================================================================


def create_llm() -> BaseChatModel:
    """Create LLM instance for analyzer agent."""
    from olav.core.llm import LLMFactory

    # Create LLM using LLMFactory (direct, no wrapper needed)
    return LLMFactory.get_chat_model(temperature=0)


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
    if any(
        k in query_lower for k in ["current", "live", "now", "verify", "check status", "up to date"]
    ):
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
        from olav.lib.data_gateway import query_database

        # Execute SQL query directly using query_database (query_network deprecated)
        # query_database returns list[dict] directly, no JSON parsing needed
        rows = query_database(state.user_query)

        # query_database returns list[dict] directly on success
        state.db_data = {
            "data": rows,
            "sql": state.user_query,
            "row_count": len(rows),
        }

        # Search for similar historical cases (Agentic Learning)
        state.similar_cases = _search_similar_cases(state.user_query)
        if state.similar_cases:
            logger.info(f"Found {len(state.similar_cases)} similar historical cases")

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

    # Skip CLI verification for queries that are clearly database queries
    # CLI verification should only happen for real-time diagnostics, not data exports
    query_lower = state.user_query.lower()
    db_keywords = ["save", "export", "list", "show all", "get all", "version info"]
    if any(keyword in query_lower for keyword in db_keywords):
        logger.info("Skipping CLI verification for database-focused query")
        state.cli_data = {"skipped": "Database-only query"}
        state.status = "analyzing"
        return state

    try:
        # Use Tool Registry for Skill-Centric architecture
        from olav.core.tool_registry import get_tool
        
        nornir_execute = get_tool("nornir_execute")
        
        if not nornir_execute:
            logger.warning("nornir_execute tool not found in registry")
            state.cli_data = {"skipped": "Tool not available"}
            state.status = "analyzing"
            return state

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

        # Execute command on a sample device (since nornir_execute is a tool, we invoke it)
        # Note: In production, would need proper device selection logic
        try:
            # nornir_execute is a LangChain tool, invoke it synchronously
            result = nornir_execute.invoke(
                {
                    "device": "router1",  # Default device, should be configurable
                    "command": command,
                    "timeout": settings.runtime.default_timeout,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to execute CLI command: {e}")
            result = f"CLI execution failed: {str(e)}"

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

        # Extract root cause and solution for learning (simple extraction)
        root_cause = "Unknown"
        solution = "See recommendations"

        # Try to extract structured information from analysis
        lines = analysis.split("\n")
        for i, line in enumerate(lines):
            if "root cause" in line.lower() or "根因" in line:
                root_cause = (
                    line.split(":", 1)[-1].strip()
                    if ":" in line
                    else lines[i + 1].strip()
                    if i + 1 < len(lines)
                    else line
                )
            if "solution" in line.lower() or "解决方案" in line.lower():
                solution = line.split(":", 1)[-1].strip() if ":" in line else line

        # Collect devices and commands for learning
        devices_checked = []
        commands_used = []

        if state.db_data.get("data"):
            # Extract device names from data
            for row in state.db_data["data"][:10]:
                if isinstance(row, dict):
                    if "device" in row:
                        devices_checked.append(row["device"])
                    elif "name" in row:
                        devices_checked.append(row["name"])

        if state.cli_data.get("command"):
            commands_used.append(state.cli_data["command"])

        # Save diagnosis case for future learning (Agentic Learning)
        try:
            _save_diagnosis_case(
                symptom=state.user_query,
                root_cause=root_cause,
                solution=solution,
                devices_checked=list(set(devices_checked)),  # Deduplicate
                commands_used=commands_used,
            )
        except Exception as e:
            logger.warning(f"Failed to save diagnosis case: {e}")

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

    Phase 2: Load system prompt from SKILL.md instead of hardcoding.

    Args:
        state: Current agent state

    Returns:
        Analysis prompt
    """
    # Phase 2: Load system prompt from SKILL.md
    try:
        from olav.core.subagent_loader import load_skill_prompt

        system_prompt = load_skill_prompt("network-analysis", "system")
    except Exception as e:
        logger.warning(f"Failed to load system prompt from SKILL.md: {e}")
        # Fallback to simple prompt if SKILL.md not available
        system_prompt = "You are a Network Analysis Specialist providing expert insights."

    prompt_parts = [
        system_prompt,
        "",
        "Data Sources:",
    ]

    # Add similar historical cases (Agentic Learning)
    if state.similar_cases:
        prompt_parts.append("0. Similar Historical Cases (for reference):")
        for i, case in enumerate(state.similar_cases[:3], 1):
            age = case.get("age_days", 0)
            prompt_parts.append(f"   Case {i} ({age} days ago):")
            prompt_parts.append(f"     Symptom: {case.get('symptom', 'Unknown')}")
            prompt_parts.append(f"     Root Cause: {case.get('root_cause', 'Unknown')}")
            prompt_parts.append(f"     Solution: {case.get('solution', 'Unknown')}")
        prompt_parts.append(
            "   ⚠️ Important: Historical cases are for reference only. Verify in current state."
        )
        prompt_parts.append("")

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


def _search_similar_cases(symptom: str, skill_name: str = "network-expert") -> list[dict[str, Any]]:
    """Search for similar historical diagnosis cases.

    Args:
        symptom: User's problem description
        skill_name: Name of the skill

    Returns:
        List of similar cases
    """
    try:
        # Extract keywords from symptom (simple implementation)
        keywords = [w for w in symptom.split() if len(w) > 3][:3]
        similar_cases = []

        for keyword in keywords:
            cases = _gw.search_similar_cases(skill_name, symptom=keyword, max_age_days=30, limit=2)
            similar_cases.extend(cases)

        # Deduplicate by case content
        seen = set()
        unique_cases = []
        for case in similar_cases:
            key = (case.get("symptom", ""), case.get("root_cause", ""))
            if key not in seen:
                seen.add(key)
                unique_cases.append(case)

        return unique_cases[:5]  # Return top 5
    except Exception as e:
        logger.warning(f"Failed to search similar cases: {e}")
        return []


def _build_diagnosis_context(symptom: str, similar_cases: list[dict[str, Any]]) -> str:
    """Build diagnosis context including historical cases.

    Args:
        symptom: Current problem symptom
        similar_cases: List of similar historical cases

    Returns:
        Context string with historical cases
    """
    context = f"当前问题: {symptom}\n"

    if similar_cases:
        context += "\n相似历史案例 (仅供参考，需验证当前状态):\n"
        for case in similar_cases:
            age = case.get("age_days", 0)
            context += f"""
- 时间: {case.get("created_at", "Unknown")} ({age} 天前)
  症状: {case.get("symptom", "Unknown")}
  根因: {case.get("root_cause", "Unknown")}
  解决方案: {case.get("solution", "Unknown")}
"""
        context += "\n⚠️ 重要: 历史案例仅供参考，必须在当前状态中验证。\n"
    else:
        context += "\n未找到相似历史案例。\n"

    return context


def _save_diagnosis_case(
    symptom: str,
    root_cause: str,
    solution: str,
    devices_checked: list[str] | None = None,
    commands_used: list[str] | None = None,
    skill_name: str = "network-expert",
) -> None:
    """Save diagnosis case to learning database.

    Args:
        symptom: Problem symptom
        root_cause: Identified root cause
        solution: Applied solution
        devices_checked: List of devices examined
        commands_used: List of commands executed
        skill_name: Name of the skill
    """
    try:
        _gw.save_diagnosis_case(
            skill_name=skill_name,
            symptom=symptom,
            devices_checked=devices_checked or [],
            commands_used=commands_used or [],
            root_cause=root_cause,
            solution=solution,
        )
        logger.info(f"Saved diagnosis case for: {symptom}")
    except Exception as e:
        logger.warning(f"Failed to save diagnosis case: {e}")


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

    return workflow.compile()  # type: ignore[return-value]


@tool
async def analyze_network(
    user_query: str,
) -> str:
    """Analyze network using Analyzer Agent with Data Fusion logic.

    Implements:
    1. Static First: Always query DuckDB snapshot first (Instant access)
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


def create_analyzer_agent(model: str | None = None) -> Callable[[str], str]:
    """Create a simple wrapper for backward compatibility.

    Args:
        model: LLM model name (None = use settings.agent.analyzer_model)

    Returns:
        Callable agent
    """
    import asyncio

    from config.settings import settings

    # Use settings if model not specified
    if model is None:
        model = settings.agent.analyzer_model

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

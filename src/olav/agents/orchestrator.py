"""Orchestrator Agent - ReAct-based Meta-Agent.

The Orchestrator is the central coordinator that:
1. Routes user queries to appropriate specialists
2. Executes ReAct loops for complex multi-step tasks
3. Implements fallback strategies (SQL -> CLI)
4. Aggregates and synthesizes results from multiple specialists

Architecture:
- Tier 0: Semantic Cache (instant responses)
- Tier 1: Fast Router (direct specialist dispatch)
- Tier 2: ReAct Orchestrator (multi-step reasoning)

Roadmap: Phase 2 - Orchestrator & Router
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from olav.core.query_router import QueryRouter, RoutingDecision

logger = logging.getLogger(__name__)


# =============================================================================
# State Definition
# =============================================================================


@dataclass
class OrchestratorState:
    """State for the Orchestrator Agent.

    Attributes:
        user_query: User's natural language query
        routing_decision: Routing decision from QueryRouter
        step_results: Results from each specialist execution step
        final_answer: Synthesized final answer
        status: Current status in the workflow
        error_message: Error message if failed
        iteration: Current ReAct iteration (for multi-step loops)
        max_iterations: Maximum allowed iterations
    """

    user_query: str = ""
    routing_decision: RoutingDecision | None = None
    step_results: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    status: str = "pending"  # pending, routing, executing, fallback, synthesizing, complete, failed
    error_message: str = ""
    iteration: int = 0
    max_iterations: int = 10


# =============================================================================
# Orchestrator Nodes
# =============================================================================


def create_llm() -> ChatOpenAI:
    """Create LLM instance for orchestrator.

    Returns:
        ChatOpenAI instance
    """
    from olav.core.llm_interface import MapReduceLLM

    # Use standard settings via MapReduceLLM
    mr = MapReduceLLM(provider="openai")
    return mr.llm


async def route_node(state: OrchestratorState, router: QueryRouter | None = None) -> OrchestratorState:
    """Route user query to appropriate specialist.

    Args:
        state: Current agent state
        router: QueryRouter instance (if None, creates default)

    Returns:
        Updated state with routing decision
    """
    logger.info(f"Routing query: {state.user_query[:50]}...")

    state.status = "routing"

    try:
        if router is None:
            router = QueryRouter()

        decision = router.route(state.user_query)
        state.routing_decision = decision

        # Determine next status based on decision
        if decision.action == "reject":
            state.status = "failed"
            state.error_message = decision.message or "Query rejected by guard"
        elif decision.action == "require_approval":
            state.status = "failed"
            state.error_message = decision.message or "Approval required"
        else:
            state.status = "executing"

        logger.info(f"Routing decision: {decision.expert} ({decision.action})")

    except Exception as e:
        state.error_message = f"Routing failed: {e}"
        state.status = "failed"
        logger.error(state.error_message)

    return state


async def execute_node(
    state: OrchestratorState,
    agent: Any | None = None,
) -> OrchestratorState:
    """Execute query using the selected specialist.

    Args:
        state: Current agent state
        agent: Specialist agent instance (if None, creates default based on routing)

    Returns:
        Updated state with execution result
    """
    logger.info(f"Executing with specialist: {state.routing_decision.expert}")

    state.status = "executing"
    state.iteration += 1

    try:
        # Get the appropriate specialist agent
        if agent is None:
            agent = _get_specialist_agent(state.routing_decision.expert)

        # Execute the query
        result = await agent.ainvoke(HumanMessage(content=state.user_query))

        # Store result
        step_result = {
            "expert": state.routing_decision.expert,
            "action": state.routing_decision.action,
            "tool": state.routing_decision.tool,
            "result": str(result.content) if isinstance(result, AIMessage) else str(result),
            "iteration": state.iteration,
        }
        state.step_results.append(step_result)

        # Check if we need fallback
        if _should_fallback(state, result):
            state.status = "fallback"
            logger.info("Primary execution failed, initiating fallback")
        else:
            state.status = "synthesizing"
            logger.info("Execution successful, proceeding to synthesis")

    except Exception as e:
        logger.error(f"Execution failed: {e}")
        state.step_results.append(
            {
                "expert": state.routing_decision.expert,
                "error": str(e),
                "iteration": state.iteration,
            }
        )

        # Attempt fallback if available
        if state.routing_decision.fallback and state.iteration < state.max_iterations:
            state.status = "fallback"
        else:
            state.status = "failed"
            state.error_message = f"Execution failed: {e}"

    return state


async def fallback_node(
    state: OrchestratorState,
    agent: Any | None = None,
) -> OrchestratorState:
    """Execute fallback strategy (typically SQL -> CLI).

    Args:
        state: Current agent state
        agent: Fallback agent instance

    Returns:
        Updated state with fallback result
    """
    logger.info("Executing fallback strategy")

    state.status = "fallback"
    state.iteration += 1

    try:
        # Determine fallback expert
        fallback_expert = state.routing_decision.fallback or "cli"

        # Get fallback agent
        if agent is None:
            agent = _get_specialist_agent(fallback_expert)

        # Execute fallback
        result = await agent.ainvoke(HumanMessage(content=state.user_query))

        # Store fallback result
        state.step_results.append(
            {
                "expert": fallback_expert,
                "result": str(result.content) if isinstance(result, AIMessage) else str(result),
                "fallback": True,
                "iteration": state.iteration,
            }
        )

        state.status = "synthesizing"
        logger.info("Fallback execution successful")

    except Exception as e:
        logger.error(f"Fallback failed: {e}")
        state.step_results.append(
            {
                "expert": "fallback",
                "error": str(e),
                "iteration": state.iteration,
            }
        )

        # Give up if fallback also fails
        state.status = "failed"
        state.error_message = f"Both primary and fallback failed: {e}"

    return state


async def synthesize_node(
    state: OrchestratorState,
    llm: ChatOpenAI | None = None,
) -> OrchestratorState:
    """Synthesize results from multiple specialists into final answer.

    Args:
        state: Current agent state
        llm: LLM instance for synthesis

    Returns:
        Updated state with final answer
    """
    logger.info("Synthesizing results")

    state.status = "synthesizing"

    try:
        if llm is None:
            llm = create_llm()

        # Build synthesis prompt
        prompt = _build_synthesis_prompt(state)

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=state.user_query),
        ]

        response = await llm.ainvoke(messages)

        state.final_answer = response.content if isinstance(response.content, str) else str(response.content)
        state.status = "complete"

        logger.info("Synthesis completed successfully")

    except Exception as e:
        # Fallback to simple concatenation if LLM synthesis fails
        logger.warning(f"LLM synthesis failed, using simple aggregation: {e}")
        state.final_answer = _simple_synthesis(state)
        state.status = "complete"

    return state


# =============================================================================
# Helper Functions
# =============================================================================


def _get_specialist_agent(expert_name: str) -> Any:
    """Get specialist agent by name.

    Args:
        expert_name: Name of the specialist (database, cli, analysis, etc.)

    Returns:
        Agent instance

    Raises:
        ValueError: If expert not found
    """
    from olav.agents.query_agent_v2 import QueryAgentV2
    from olav.tools.react_query import query_network

    if expert_name == "database":
        # Use QueryAgentV2 with database tools
        return QueryAgentV2(tools=[query_network], model="gpt-4o")

    elif expert_name == "cli":
        # Load network-query skill with all tools including smart_query for CLI fallback
        # This gives agent access to: query_database, inspect_schema, smart_query, etc.
        return QueryAgentV2(skill_name="network-query", mode="standard")

    elif expert_name == "analysis":
        # Use Analyzer agent
        from olav.agents.analyzer import analyze_network

        # Return a wrapper that makes it compatible with ainvoke
        class AgentWrapper:
            def __init__(self, tool):
                self.tool = tool

            async def ainvoke(self, message):
                result = await self.tool.ainvoke({"user_query": message.content})
                return AIMessage(content=result)

        return AgentWrapper(analyze_network)

    else:
        # Default to database agent
        logger.warning(f"Unknown expert '{expert_name}', defaulting to database")
        return QueryAgentV2(tools=[query_network], model="gpt-4o")


def _should_fallback(state: OrchestratorState, result: Any) -> bool:
    """Determine if fallback should be triggered.

    Args:
        state: Current agent state
        result: Execution result

    Returns:
        True if fallback should be triggered
    """
    # Check if fallback is configured
    if not state.routing_decision.fallback:
        return False

    # Check if result indicates failure
    if isinstance(result, AIMessage):
        content = result.content.lower()
        error_indicators = ["error", "failed", "not found", "no results", "empty"]
        return any(indicator in content for indicator in error_indicators)

    # Check last step result for errors
    if state.step_results:
        last_result = state.step_results[-1]
        if "error" in last_result:
            return True

    return False


def _build_synthesis_prompt(state: OrchestratorState) -> str:
    """Build synthesis prompt.

    Args:
        state: Current agent state

    Returns:
        Synthesis prompt
    """
    prompt_parts = [
        "You are an Orchestrator synthesizing results from multiple network specialists.",
        "",
        "User Query:",
        state.user_query,
        "",
        f"Execution Steps ({len(state.step_results)}):",
    ]

    for i, step in enumerate(state.step_results, 1):
        expert = step.get("expert", "unknown")
        result = step.get("result", step.get("error", "No result"))
        fallback_mark = " [FALLBACK]" if step.get("fallback") else ""
        prompt_parts.append(f"\n{i}. {expert}{fallback_mark}:")
        prompt_parts.append(f"   {result[:200]}...")  # Truncate long results

    prompt_parts.extend(
        [
            "",
            "Your task:",
            "1. Synthesize the results into a coherent answer",
            "2. Highlight key findings",
            "3. Note any discrepancies between specialists",
            "4. Provide actionable recommendations",
            "",
            "Format your response as:",
            "## Summary",
            "[Concise summary]",
            "",
            "## Key Findings",
            "- [Finding 1]",
            "- [Finding 2]",
            "",
            "## Recommendations",
            "- [Recommendation 1]",
            "- [Recommendation 2]",
        ]
    )

    return "\n".join(prompt_parts)


def _simple_synthesis(state: OrchestratorState) -> str:
    """Simple fallback synthesis without LLM.

    Args:
        state: Current agent state

    Returns:
        Synthesized answer
    """
    parts = ["## Execution Results\n"]

    for i, step in enumerate(state.step_results, 1):
        expert = step.get("expert", "unknown")
        result = step.get("result", step.get("error", "No result"))
        parts.append(f"### {i}. {expert}")
        parts.append(result)
        parts.append("")

    return "\n".join(parts)


# =============================================================================
# Graph Creation
# =============================================================================


def create_orchestrator_graph() -> StateGraph:
    """Create the Orchestrator Agent workflow graph.

    Returns:
        LangGraph StateGraph
    """
    workflow = StateGraph(OrchestratorState)

    # Add nodes
    workflow.add_node("route", route_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("fallback", fallback_node)
    workflow.add_node("synthesize", synthesize_node)

    # Add edges
    workflow.set_entry_point("route")

    # Conditional routing from route node
    workflow.add_conditional_edges(
        "route",
        lambda s: s.status,
        {
            "executing": "execute",
            "failed": END,
        },
    )

    # Conditional routing from execute node
    workflow.add_conditional_edges(
        "execute",
        lambda s: s.status,
        {
            "synthesizing": "synthesize",
            "fallback": "fallback",
            "failed": END,
        },
    )

    # Conditional routing from fallback node
    workflow.add_conditional_edges(
        "fallback",
        lambda s: s.status,
        {
            "synthesizing": "synthesize",
            "failed": END,
        },
    )

    workflow.add_edge("synthesize", END)

    return workflow.compile()


# =============================================================================
# Main Interface
# =============================================================================


async def orchestrate_query(user_query: str, router: QueryRouter | None = None) -> dict[str, Any]:
    """Orchestrate a user query through the complete workflow.

    Args:
        user_query: User's natural language query
        router: Optional QueryRouter instance

    Returns:
        Dictionary containing:
            - status: final status (complete, failed)
            - final_answer: synthesized answer
            - step_results: list of individual specialist results
            - error_message: error if failed
    """
    logger.info(f"Orchestrating query: {user_query[:50]}...")

    try:
        # Create graph
        app = create_orchestrator_graph()

        # Initial state
        initial_state = OrchestratorState(user_query=user_query)

        # Execute graph with router injection
        # Note: We need to pass the router to the route_node
        # This is a simplified version - in production, use proper dependency injection
        result = await app.ainvoke(initial_state)

        return {
            "status": result.status,
            "final_answer": result.final_answer,
            "step_results": result.step_results,
            "error_message": result.error_message,
        }

    except Exception as e:
        logger.error(f"Orchestration failed: {e}")
        return {
            "status": "failed",
            "final_answer": "",
            "step_results": [],
            "error_message": str(e),
        }


# =============================================================================
# Main
# =============================================================================


if __name__ == "__main__":
    import asyncio

    async def test() -> None:
        # Test query
        test_query = "List all devices with high CPU usage"
        result = await orchestrate_query(test_query)

        print(f"Query: {test_query}")
        print(f"Status: {result['status']}")
        print(f"Final Answer:\n{result['final_answer']}")

    asyncio.run(test())

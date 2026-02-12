"""Orchestrator Dependency Executor - Collaboration & Dependency Management (v0.11.1)

Separated from orchestrator.py as part of code simplification refactor (Phase 2.1).

Responsibilities:
- Parse collaborative mode directives
- Build dependency graphs
- Execute tasks in topologically sorted order
- Handle agent dependencies and data flow
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _parse_collaborative_mode(agent_response: str) -> dict[str, Any]:
    """Parse collaborative mode JSON from agent response.

    Format:
        {
            "@collaborative": true,
            "@mode": "query|cli|expert",
            "@requires": ["agent1", "agent2"],
            "result": {...}
        }

    Args:
        agent_response: Agent response string

    Returns:
        Parsed collaborative mode dict or empty dict if not in collaborative mode
    """
    import json

    try:
        # Try to parse as JSON
        data = json.loads(agent_response)

        # Check for collaborative marker
        if isinstance(data, dict) and data.get("@collaborative") is True:
            logger.debug(f"✓ Collaborative mode detected: {data.get('@mode')}")
            return data

        return {}
    except (json.JSONDecodeError, ValueError):
        # Not JSON or not in collaborative format
        return {}


def _build_dependency_graph(agents: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build dependency graph from agent list.

    Args:
        agents: List of agent configs with '@requires' field

    Returns:
        Dict mapping agent name to list of dependent agents
    """
    graph = {}

    for agent in agents:
        name = agent.get("@agent_name") or agent.get("name")
        requires = agent.get("@requires", [])

        if name:
            graph[name] = requires
            logger.debug(f"Agent '{name}' depends on: {requires}")

    return graph


def _topological_sort(graph: dict[str, list[str]]) -> list[str]:
    """Topologically sort agents based on dependencies.

    Args:
        graph: Dependency graph (agent -> [dependencies])

    Returns:
        Topologically sorted list of agent names
    """
    from collections import deque

    # Calculate in-degrees
    in_degree = {node: 0 for node in graph}
    for node in graph:
        for dep in graph[node]:
            in_degree[dep] = in_degree.get(dep, 0) + 1

    # Find all nodes with in-degree 0
    queue = deque([node for node in in_degree if in_degree[node] == 0])
    sorted_list = []

    while queue:
        node = queue.popleft()
        sorted_list.append(node)

        # Reduce in-degree for dependent nodes
        for dependent in graph.get(node, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(sorted_list) != len(graph):
        logger.warning("⚠️ Dependency graph has cycles - using original order")
        return list(graph.keys())

    logger.debug(f"Topologically sorted agents: {sorted_list}")
    return sorted_list


async def _execute_with_dependencies_order(
    user_query: str,
    agents: dict[str, Any],
    mode: str = "sequential",
) -> dict[str, Any]:
    """Execute agents in dependency order with data flow.

    Args:
        user_query: Original user query
        agents: Dict of agent executors (agent_name -> executor_function)
        mode: Execution mode - "sequential" or "concurrent"

    Returns:
        Aggregated results from all agents
    """
    if mode not in ("sequential", "concurrent"):
        logger.warning(f"⚠️ Unknown execution mode '{mode}' - using 'sequential'")
        mode = "sequential"

    # Build execution order
    graph = _build_dependency_graph(
        [{"name": name, "@requires": []} for name in agents.keys()]
    )
    execution_order = _topological_sort(graph)

    results = {}
    execution_log = []

    if mode == "sequential":
        # Sequential execution - each agent waits for dependencies
        for agent_name in execution_order:
            if agent_name not in agents:
                logger.warning(f"⚠️ Agent '{agent_name}' not found in executor map")
                continue

            try:
                # Get dependent agent results
                dep_results = {
                    dep: results.get(dep)
                    for dep in graph.get(agent_name, [])
                    if dep in results
                }

                # Execute agent with dependency results
                executor = agents[agent_name]
                agent_result = await executor(user_query, dep_results)

                results[agent_name] = agent_result
                execution_log.append(
                    {
                        "agent": agent_name,
                        "status": "success",
                        "timestamp": str(__import__("datetime").datetime.now()),
                    }
                )
                logger.info(f"✓ Executed agent: {agent_name}")
            except Exception as e:
                logger.error(f"✗ Agent '{agent_name}' failed: {type(e).__name__}: {e}")
                execution_log.append(
                    {
                        "agent": agent_name,
                        "status": "error",
                        "error": str(e),
                        "timestamp": str(__import__("datetime").datetime.now()),
                    }
                )

    elif mode == "concurrent":
        # Concurrent execution - execute all agents simultaneously
        try:
            tasks = {
                agent_name: agents[agent_name](user_query, {})
                for agent_name in execution_order
                if agent_name in agents
            }

            concurrent_results = await asyncio.gather(*tasks.values(), return_exceptions=True)

            for agent_name, result in zip(tasks.keys(), concurrent_results):
                if isinstance(result, Exception):
                    logger.error(f"✗ Concurrent agent '{agent_name}' failed: {result}")
                    execution_log.append(
                        {
                            "agent": agent_name,
                            "status": "error",
                            "error": str(result),
                        }
                    )
                else:
                    results[agent_name] = result
                    execution_log.append(
                        {
                            "agent": agent_name,
                            "status": "success",
                        }
                    )

        except Exception as e:
            logger.error(f"✗ Concurrent execution failed: {type(e).__name__}: {e}")

    return {
        "results": results,
        "execution_order": execution_order,
        "execution_log": execution_log,
        "mode": mode,
    }

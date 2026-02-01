"""
ReAct Agent Tools Wrapper (Legacy Compatibility)

This module provides compatibility functions for the ReAct architecture,
wrapping the new Skill-Centric QueryAgentV2.
"""

from typing import Any

from olav.agents.query_agent_v2 import QueryAgentV2


async def run_react_agent(query_text: str, **kwargs: Any) -> str:
    """Run a natural language query through the ReAct agent.

    Args:
        query_text: The user's natural language question.
        **kwargs: Additional parameters for the agent.

    Returns:
        The agent's markdown response.
    """
    agent = QueryAgentV2()
    # ainvoke returns a dict with 'result'
    result = await agent.ainvoke({"messages": [{"role": "user", "content": query_text}]})
    return result.get("result", "No result returned.") or f"Error: {result.get('error')}"


class ReActAgent:
    """Compatibility class for ReActAgent mentioned in some roadmaps"""

    def __init__(self, **kwargs: Any) -> None:
        self.agent = QueryAgentV2()

    async def ainvoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return await self.agent.ainvoke(inputs)

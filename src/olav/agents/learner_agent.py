"""Learner Agent - captures successful resolution paths into episodic memory index."""
from typing import List, Dict, Any
from deepagents import SubAgent
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.language import BaseLanguageModel

from olav.core.prompt_manager import prompt_manager
from olav.tools.opensearch_tool import store_episodic_memory


def create_learner_subagent(model: BaseLanguageModel, checkpointer: PostgresSaver) -> SubAgent:
    """Create learner subagent responsible for writing memory entries.

    It expects the parent to supply context such as user_intent and resolved_actions
    in state; those will be packaged and persisted via store_episodic_memory tool.
    """
    return SubAgent(
        name="learner-agent",
        tools=[store_episodic_memory],
        checkpointer=checkpointer,
        model=model,
        system_prompt=prompt_manager.load_agent_prompt("learner_agent"),
    )

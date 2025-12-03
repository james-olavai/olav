"""Multi-Agent Orchestrator - Hub-and-Spoke Architecture.

Routes user queries to specialized agents based on intent classification:
- Query Agent: Read-only information retrieval (3 tools)
- Diagnose Agent: Problem analysis and root cause (4 tools)
- Config Agent: Configuration changes with HITL (3 tools)

This is the new architecture following LangChain best practices:
- Each agent has 3-7 tools (optimal for LLM decision making)
- Hub-and-Spoke: All results return to Root Orchestrator
- Supports Agent Handoff (Diagnose → Config)

For backward compatibility, the existing WorkflowOrchestrator is preserved.
"""

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, Field

from olav.agents.config_agent import ConfigAgent
from olav.agents.diagnose_agent import DiagnoseAgent
from olav.agents.intent_classifier import Intent, get_intent_classifier
from olav.agents.query_agent import QueryAgent
from olav.core.settings import settings

logger = logging.getLogger(__name__)


class OrchestratorResult(BaseModel):
    """Result from multi-agent orchestration."""

    intent: Intent
    agent_used: str
    messages: list[Any] = Field(default_factory=list)
    result: dict = Field(default_factory=dict)
    handoff_occurred: bool = False
    handoff_agent: str | None = None
    hitl_pending: bool = False


class MultiAgentOrchestrator:
    """Hub-and-Spoke Multi-Agent Orchestrator.

    Architecture:
    ```
                    User Query
                         │
                         ▼
                ┌────────────────┐
                │ Intent         │
                │ Classifier     │
                └───────┬────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
    ┌───────┐     ┌───────────┐   ┌─────────┐
    │ Query │     │ Diagnose  │   │ Config  │
    │ Agent │     │ Agent     │   │ Agent   │
    │(3 tools)    │(4 tools)  │   │(3 tools)│
    └───┬───┘     └─────┬─────┘   └────┬────┘
        │               │              │
        │               │    Handoff   │
        │               └──────────────┤
        │                              │
        └──────────────┬───────────────┘
                       │
                       ▼
                ┌────────────────┐
                │ HITL Checkpoint│
                │ (if needed)    │
                └────────────────┘
    ```

    Features:
    - LLM-based intent classification (replaces keyword matching)
    - 3-7 tools per agent (LangChain best practice)
    - Agent Handoff support (Diagnose → Config)
    - Unified HITL handling for all write operations
    """

    def __init__(self, checkpointer: BaseCheckpointSaver | None = None):
        """Initialize Multi-Agent Orchestrator.

        Args:
            checkpointer: LangGraph checkpointer for state persistence
        """
        self.checkpointer = checkpointer
        self.intent_classifier = get_intent_classifier()

        # Initialize specialized agents
        self.query_agent = QueryAgent(checkpointer=checkpointer)
        self.diagnose_agent = DiagnoseAgent(checkpointer=checkpointer)
        self.config_agent = ConfigAgent(checkpointer=checkpointer)

        logger.info(
            f"MultiAgentOrchestrator initialized with agents: "
            f"Query({self.query_agent.tools_count} tools), "
            f"Diagnose({self.diagnose_agent.tools_count} tools), "
            f"Config({self.config_agent.tools_count} tools)"
        )

    async def route(self, user_query: str, thread_id: str | None = None) -> OrchestratorResult:
        """Route user query to appropriate agent based on intent.

        Args:
            user_query: User's natural language query
            thread_id: Optional thread ID for conversation continuity

        Returns:
            OrchestratorResult with agent output and metadata
        """
        # Step 1: Classify intent
        intent = await self.intent_classifier.classify(user_query)
        logger.info(
            f"Intent classified: primary={intent.primary}, "
            f"secondary={intent.secondary}, "
            f"confidence={intent.confidence:.2f}"
        )

        # Step 2: Route to primary agent
        if intent.primary == "query":
            agent_used = "query_agent"
            result = await self.query_agent.run(user_query, thread_id)
        elif intent.primary == "diagnose":
            agent_used = "diagnose_agent"
            result = await self.diagnose_agent.run(user_query, thread_id)
        elif intent.primary == "config":
            agent_used = "config_agent"
            result = await self.config_agent.run(user_query, thread_id)
        else:
            # Default to query (safest)
            agent_used = "query_agent"
            result = await self.query_agent.run(user_query, thread_id)

        # Step 3: Check for Agent Handoff
        handoff_occurred = False
        handoff_agent = None

        if agent_used == "diagnose_agent" and intent.secondary == "config":
            # Check if diagnosis result suggests config change
            diagnosis_result = result.get("diagnosis_result")
            if diagnosis_result and getattr(diagnosis_result, "needs_config_change", False):
                logger.info("Handoff triggered: Diagnose → Config")
                handoff_occurred = True
                handoff_agent = "config_agent"

                # Execute config agent with diagnosis context
                config_result = await self.config_agent.run(
                    query=getattr(diagnosis_result, "suggested_fix", user_query),
                    thread_id=thread_id,
                    context={
                        "root_cause": getattr(diagnosis_result, "root_cause", ""),
                        "affected_devices": getattr(diagnosis_result, "affected_devices", []),
                        "suggested_fix": getattr(diagnosis_result, "suggested_fix", ""),
                    },
                )

                # Merge results
                result = self._merge_results(result, config_result)

        # Step 4: Check HITL pending
        hitl_pending = result.get("hitl_pending", False) or intent.requires_hitl

        return OrchestratorResult(
            intent=intent,
            agent_used=agent_used,
            messages=result.get("messages", []),
            result=result,
            handoff_occurred=handoff_occurred,
            handoff_agent=handoff_agent,
            hitl_pending=hitl_pending,
        )

    def _merge_results(self, diagnose_result: dict, config_result: dict) -> dict:
        """Merge diagnosis and config results after handoff.

        Args:
            diagnose_result: Result from Diagnose Agent
            config_result: Result from Config Agent (after handoff)

        Returns:
            Merged result dict
        """
        diagnose_messages = diagnose_result.get("messages", [])
        config_messages = config_result.get("messages", [])

        # Add handoff marker
        handoff_marker = AIMessage(content="--- 配置代理接管 (Agent Handoff) ---")

        merged_messages = diagnose_messages + [handoff_marker] + config_messages

        return {
            "messages": merged_messages,
            "diagnosis_result": diagnose_result.get("diagnosis_result"),
            "config_operations": config_result.get("config_operations", []),
            "hitl_pending": config_result.get("hitl_pending", False),
        }

    async def resume(
        self,
        thread_id: str,
        user_input: str,
        agent: str,
    ) -> OrchestratorResult:
        """Resume interrupted agent execution with user input.

        Args:
            thread_id: Thread ID of interrupted execution
            user_input: User's approval/rejection/modification
            agent: Name of the agent that was interrupted

        Returns:
            OrchestratorResult after resumption
        """
        if agent == "config_agent":
            result = await self.config_agent.run(user_input, thread_id)
            return OrchestratorResult(
                intent=Intent(
                    primary="config",
                    secondary="none",
                    confidence=1.0,
                    reasoning="Resume from HITL",
                    requires_hitl=True,
                ),
                agent_used=agent,
                messages=result.get("messages", []),
                result=result,
                handoff_occurred=False,
                handoff_agent=None,
                hitl_pending=False,
            )

        # Other agents don't typically have HITL, but handle just in case
        logger.warning(f"Resume called for non-config agent: {agent}")
        return OrchestratorResult(
            intent=Intent(
                primary="query",
                secondary="none",
                confidence=0.5,
                reasoning="Unexpected resume",
                requires_hitl=False,
            ),
            agent_used=agent,
            messages=[AIMessage(content="无法恢复非配置代理的执行")],
            result={},
            handoff_occurred=False,
            handoff_agent=None,
            hitl_pending=False,
        )


async def create_multi_agent_orchestrator() -> MultiAgentOrchestrator:
    """Factory function to create Multi-Agent Orchestrator.

    Returns:
        Configured MultiAgentOrchestrator instance
    """
    # Create async checkpointer
    try:
        checkpointer_manager = AsyncPostgresSaver.from_conn_string(settings.postgres_uri)
        checkpointer = await checkpointer_manager.__aenter__()
        await checkpointer.setup()
        logger.info("AsyncPostgresSaver initialized for MultiAgentOrchestrator")
    except Exception as e:
        logger.warning(f"Failed to create async checkpointer: {e}, using None")
        checkpointer = None

    return MultiAgentOrchestrator(checkpointer=checkpointer)


__all__ = ["MultiAgentOrchestrator", "OrchestratorResult", "create_multi_agent_orchestrator"]

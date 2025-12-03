"""Agent implementations using workflow orchestrator pattern.

The agent architecture has transitioned from DeepAgents to a custom
workflow-based orchestration system using LangGraph StateGraph.

Multi-Agent Architecture (NEW):
    - IntentClassifier: LLM-based intent classification
    - QueryAgent: Read-only information retrieval (3 tools)
    - DiagnoseAgent: Problem analysis and root cause (4 tools)
    - ConfigAgent: Configuration changes with HITL (3 tools)
    - MultiAgentOrchestrator: Hub-and-Spoke routing

Legacy Entry Point (for backward compatibility):
    - root_agent_orchestrator.create_workflow_orchestrator()
"""

from olav.agents.base import AgentProtocol, BaseAgent
from olav.agents.config_agent import ConfigAgent
from olav.agents.diagnose_agent import DiagnoseAgent
from olav.agents.intent_classifier import Intent, IntentClassifier, get_intent_classifier
from olav.agents.multi_agent_orchestrator import (
    MultiAgentOrchestrator,
    OrchestratorResult,
    create_multi_agent_orchestrator,
)
from olav.agents.query_agent import QueryAgent

__all__ = [
    # Base
    "AgentProtocol",
    "BaseAgent",
    # Specialized Agents
    "QueryAgent",
    "DiagnoseAgent",
    "ConfigAgent",
    # Intent Classification
    "Intent",
    "IntentClassifier",
    "get_intent_classifier",
    # Multi-Agent Orchestrator
    "MultiAgentOrchestrator",
    "OrchestratorResult",
    "create_multi_agent_orchestrator",
]

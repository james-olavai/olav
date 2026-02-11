"""
Expert Agent Integration Module

Integration layer between Expert Agent, Orchestrator, and Query Guard.

Components:
- QueryGuardIntegration: Main integration with Guard
- ExpertAgentOrchestration: Complete workflow orchestration
- HumanReviewQueue: Manages REVIEW queue
- EscalationQueue: Manages REJECT queue
- Factory functions for different deployment environments
"""

from .expert_agent_integration import (
    EscalationQueue,
    ExpertAgentOrchestration,
    HumanReviewQueue,
    QueryGuardIntegration,
    create_development_integration,
    create_production_integration,
    create_staging_integration,
)

__all__ = [
    "QueryGuardIntegration",
    "ExpertAgentOrchestration",
    "HumanReviewQueue",
    "EscalationQueue",
    "create_production_integration",
    "create_staging_integration",
    "create_development_integration",
]

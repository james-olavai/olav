"""Network Relevance Guard - LLM-based pre-filter for non-network queries.

This module provides an LLM-based guard that determines if a user query
is related to network operations. Non-network queries are rejected early to
avoid expensive downstream reasoning cycles.

The guard uses a lightweight LLM call with structured output for fast,
accurate classification.

Usage:
    guard = NetworkRelevanceGuard()

    # Check if query is network-related
    result = await guard.check(user_query)
    if not result.is_relevant:
        return f"抱歉，我是网络运维助手 OLAV，无法回答此问题：{result.reason}"
"""

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from olav.core.llm import LLMFactory
from olav.core.prompt_manager import prompt_manager

logger = logging.getLogger(__name__)


class RelevanceResult(BaseModel):
    """Result of network relevance check."""

    is_relevant: bool = Field(description="Whether the query is network-related")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the relevance decision"
    )
    reason: str = Field(
        default="",
        description="Reason for the decision (especially for rejection)"
    )
    method: Literal["llm", "fallback"] = Field(
        default="llm",
        description="Method used for classification"
    )


class LLMRelevanceDecision(BaseModel):
    """Structured output for LLM relevance check."""

    is_network_related: bool = Field(
        description="True if query is about network/infrastructure operations, False otherwise"
    )
    confidence: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Confidence score for the decision"
    )
    reasoning: str = Field(
        description="Brief explanation for the decision (1-2 sentences)"
    )


class NetworkRelevanceGuard:
    """
    LLM-based pre-filter to detect non-network queries.

    This guard prevents expensive LLM reasoning on irrelevant queries like
    "1+1=?" or "今天天气怎么样?".

    Uses a fast, focused LLM call with structured output.
    """

    def __init__(self):
        """Initialize the guard with LLM."""
        self._llm = None  # Lazy initialization

    @property
    def llm(self):
        """Lazy-load LLM only when needed."""
        if self._llm is None:
            self._llm = LLMFactory.get_chat_model(json_mode=True, reasoning=False)
        return self._llm

    def _get_system_prompt(self) -> str:
        """Load system prompt from config or use fallback."""
        try:
            # Try new prompt system first (overrides/ → _defaults/)
            return prompt_manager.load("network_guard", thinking=False)
        except FileNotFoundError:
            # Fallback to legacy location
            try:
                return prompt_manager.load_prompt("agents", "network_relevance_guard")
            except Exception:
                return self._get_fallback_prompt()

    def _get_fallback_prompt(self) -> str:
        """Fallback prompt if config not available."""
        return """You are a pre-filter for the OLAV network operations system. Your task is to quickly determine if a user query is related to network operations.

## Network operations related queries (return is_network_related=true):

1. **Network device operations**: Routers, switches, firewalls, load balancers - query, configuration, diagnostics
2. **Network protocols**: BGP, OSPF, ISIS, MPLS, VXLAN, EVPN, STP, LACP, etc.
3. **Network connectivity**: Interface status, ports, VLANs, links, neighbor relationships, sessions
4. **IP networking**: IP addresses, subnets, routing tables, ARP, MAC addresses, gateways
5. **Network faults**: Connectivity issues, packet loss, latency, bandwidth, traffic anomalies
6. **Network security**: ACLs, firewall rules, NAT, VPN
7. **Device inventory**: NetBox, device inventory, racks, sites, IP allocation
8. **Network monitoring**: SuzieQ, performance metrics, alerts, logs

## Non-network operations related queries (return is_network_related=false):

1. **General Q&A**: Math calculations, weather, translation, chitchat
2. **Application layer issues**: Web applications, databases, containers, microservices (unless network connectivity is involved)
3. **Programming development**: Code writing, debugging, framework usage
4. **Other IT**: Operating systems (non-network config), storage, backup

## Decision rules:

- If query mentions specific network device names (e.g., R1, SW1, Core-Router) → related
- If query mentions network protocols or concepts → related
- If query involves IP addresses, interfaces, VLANs → related
- If query is purely chitchat or non-technical → not related
- When uncertain, lean towards related (better to allow than block)

## Output format:

Return JSON with:
- is_network_related: bool - Whether related to network operations
- confidence: float - Confidence score (0.0-1.0)
- reasoning: str - Brief reasoning (1-2 sentences)"""

    async def check(self, query: str) -> RelevanceResult:
        """
        Check if a query is network-related using LLM.

        Args:
            query: User's natural language query

        Returns:
            RelevanceResult with relevance decision and metadata
        """
        try:
            system_prompt = self._get_system_prompt()
            llm_with_structure = self.llm.with_structured_output(LLMRelevanceDecision)

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=query),
            ]

            result = await llm_with_structure.ainvoke(messages)

            logger.debug(
                f"Network relevance check: query='{query[:50]}...', "
                f"relevant={result.is_network_related}, "
                f"confidence={result.confidence:.2f}"
            )

            return RelevanceResult(
                is_relevant=result.is_network_related,
                confidence=result.confidence,
                reason=result.reasoning,
                method="llm"
            )

        except Exception as e:
            logger.error(f"Network relevance check failed: {e}")
            # On failure, default to relevant (allow through) - fail open
            return RelevanceResult(
                is_relevant=True,
                confidence=0.5,
                reason=f"Check failed, defaulting to allow: {str(e)[:50]}",
                method="fallback"
            )


# Singleton instance
_guard: NetworkRelevanceGuard | None = None


def get_network_guard() -> NetworkRelevanceGuard:
    """Get or create the singleton guard instance."""
    global _guard
    if _guard is None:
        _guard = NetworkRelevanceGuard()
    return _guard


# Pre-defined rejection message
REJECTION_MESSAGE = """Sorry, I am OLAV (Network Operations Assistant), specialized in handling network devices and infrastructure related questions.

I can help you with:
🔍 Query network device status (BGP, OSPF, interfaces, etc.)
🔧 Diagnose network faults and troubleshoot issues
⚙️ Configure network devices (requires approval)
📦 Manage device inventory (NetBox)

If you have network-related questions, please rephrase your request."""


__all__ = [
    "NetworkRelevanceGuard",
    "RelevanceResult",
    "get_network_guard",
    "REJECTION_MESSAGE",
]

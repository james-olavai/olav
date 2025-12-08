"""Base Agent Protocol and Abstract Base Class.

Defines the interface that all specialized agents must implement.
"""

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentProtocol(Protocol):
    """Protocol defining the agent interface."""

    @property
    def name(self) -> str:
        """Agent identifier."""
        ...

    @property
    def description(self) -> str:
        """Agent purpose description."""
        ...

    @property
    def tools_count(self) -> int:
        """Number of tools this agent has."""
        ...

    async def run(self, query: str, thread_id: str | None = None) -> dict:
        """Execute agent with user query."""
        ...


class BaseAgent(ABC):
    """Abstract base class for all agents.

    Provides common functionality and enforces interface compliance.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent identifier."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Agent purpose description."""

    @property
    @abstractmethod
    def tools_count(self) -> int:
        """Number of tools this agent has (should be 3-7)."""

    @abstractmethod
    async def run(self, query: str, thread_id: str | None = None) -> dict:
        """Execute agent with user query.

        Args:
            query: User's natural language query
            thread_id: Optional thread ID for conversation continuity

        Returns:
            dict containing at minimum:
            - messages: List of conversation messages
            - Any agent-specific result fields
        """

    @abstractmethod
    def build_graph(self):
        """Build the agent's LangGraph StateGraph.

        Returns:
            Compiled LangGraph workflow
        """


__all__ = ["AgentProtocol", "BaseAgent"]

"""Agent state definitions using TypedDict."""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class AgentState(TypedDict):
    """Root agent state shared across all SubAgents."""

    messages: Annotated[list[BaseMessage], add_messages]
    device: str | None
    topology_context: dict[str, any] | None
    current_user: str
    session_id: str


class SuzieQState(TypedDict):
    """SuzieQ agent state for network analysis."""

    messages: Annotated[list[BaseMessage], add_messages]
    query_result: dict[str, any] | None
    schema_info: dict[str, any] | None


class RAGState(TypedDict):
    """RAG agent state for schema search."""

    messages: Annotated[list[BaseMessage], add_messages]
    search_results: list[dict[str, any]]
    selected_xpath: str | None


class NetConfState(TypedDict):
    """NETCONF agent state for configuration changes."""

    messages: Annotated[list[BaseMessage], add_messages]
    proposed_config: str | None
    approval_status: str | None
    execution_result: dict[str, any] | None

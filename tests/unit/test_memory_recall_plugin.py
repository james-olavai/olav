"""Phase 2-2 TDD: MemoryRecallPlugin

Assert:
- Plugin is subclass of OLAVMiddlewarePlugin
- abefore_model() returns Overwrite(enriched_messages) when memories found
- abefore_model() returns None (no-op) when no memories / embedding unavailable
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


def test_memory_recall_plugin_importable():
    from olav.plugins.middleware.memory_recall import MemoryRecallPlugin  # noqa: F401


def test_memory_recall_plugin_is_middleware_subclass():
    from langchain.agents.middleware.types import AgentMiddleware

    from olav.plugins.middleware.memory_recall import MemoryRecallPlugin

    assert issubclass(MemoryRecallPlugin, AgentMiddleware)


def test_memory_recall_plugin_name():
    from olav.plugins.middleware.memory_recall import MemoryRecallPlugin

    assert MemoryRecallPlugin.name == "memory_recall"


async def test_abefore_model_enriches_messages_when_memories_found():
    """When AutoRecallMiddleware.enrich returns enriched content, plugin returns Overwrite."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langgraph.types import Overwrite

    from olav.plugins.middleware.memory_recall import MemoryRecallPlugin

    fake_store = MagicMock()
    plugin = MemoryRecallPlugin(store=fake_store)

    original_msgs = [SystemMessage(content="be helpful"), HumanMessage(content="what is bgp?")]
    enriched_msgs = [
        SystemMessage(content="be helpful"),
        HumanMessage(content="<relevant-memories>m1</relevant-memories>\n\nwhat is bgp?"),
    ]

    state = {"messages": original_msgs}
    runtime = MagicMock()

    with patch(
        "olav.core.memory.middleware.AutoRecallMiddleware"
    ) as MockRecall:
        instance = MockRecall.return_value
        instance.enrich = AsyncMock(return_value={"messages": enriched_msgs})

        result = await plugin.abefore_model(state, runtime)

    assert result is not None, "Should return state update when memories enriched"
    assert isinstance(result["messages"], Overwrite), "Must use Overwrite to replace messages"
    assert result["messages"].value == enriched_msgs


async def test_abefore_model_returns_none_when_no_enrichment():
    """When memories are the same (no enrichment), plugin should return None."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from olav.plugins.middleware.memory_recall import MemoryRecallPlugin

    fake_store = MagicMock()
    plugin = MemoryRecallPlugin(store=fake_store)

    msgs = [SystemMessage(content="be helpful"), HumanMessage(content="what is bgp?")]
    state = {"messages": msgs}
    runtime = MagicMock()

    with patch(
        "olav.core.memory.middleware.AutoRecallMiddleware"
    ) as MockRecall:
        # enrich returns the same dict (no memories found)
        instance = MockRecall.return_value
        instance.enrich = AsyncMock(return_value={"messages": msgs})

        result = await plugin.abefore_model(state, runtime)

    assert result is None, "Should return None when messages unchanged"

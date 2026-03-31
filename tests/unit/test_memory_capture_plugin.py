"""Phase 2-3 TDD: MemoryCapturePlugin

Assert:
- Plugin is subclass of OLAVMiddlewarePlugin  
- aafter_agent() calls AutoCaptureMiddleware.process() as fire-and-forget task
- aafter_agent() returns None (no state mutation needed)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import asyncio


def test_memory_capture_plugin_importable():
    from olav.plugins.middleware.memory_capture import MemoryCapturePlugin  # noqa: F401


def test_memory_capture_plugin_is_middleware_subclass():
    from langchain.agents.middleware.types import AgentMiddleware

    from olav.plugins.middleware.memory_capture import MemoryCapturePlugin

    assert issubclass(MemoryCapturePlugin, AgentMiddleware)


def test_memory_capture_plugin_name():
    from olav.plugins.middleware.memory_capture import MemoryCapturePlugin

    assert MemoryCapturePlugin.name == "memory_capture"


async def test_aafter_agent_fires_capture_task():
    """aafter_agent should schedule AutoCaptureMiddleware.process as asyncio task."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from olav.plugins.middleware.memory_capture import MemoryCapturePlugin

    fake_store = MagicMock()
    fake_llm = MagicMock()
    plugin = MemoryCapturePlugin(store=fake_store, llm=fake_llm)

    msgs = [
        SystemMessage(content="be helpful"),
        HumanMessage(content="show bgp summary"),
        AIMessage(content="BGP is up"),
    ]
    state = {"messages": msgs}
    runtime = MagicMock()

    task_fired = []

    with patch(
        "olav.core.memory.middleware.AutoCaptureMiddleware"
    ) as MockCapture:
        mock_instance = MockCapture.return_value
        mock_instance.process = AsyncMock(side_effect=lambda *a, **kw: task_fired.append(True))
        # Reset _capture_mw so plugin creates a new instance
        plugin._capture_mw = None

        result = await plugin.aafter_agent(state, runtime)
        # Allow any background task to run
        await asyncio.sleep(0)

    # Result must be None (capture doesn't modify state)
    assert result is None, "aafter_agent must return None"
    # Process must have been scheduled/called
    assert len(task_fired) == 1, "AutoCaptureMiddleware.process must be called once"


async def test_aafter_agent_returns_none_on_empty_messages():
    """If state has no messages, plugin returns None without error."""
    from olav.plugins.middleware.memory_capture import MemoryCapturePlugin

    plugin = MemoryCapturePlugin()
    state = {"messages": []}
    runtime = MagicMock()

    result = await plugin.aafter_agent(state, runtime)
    assert result is None

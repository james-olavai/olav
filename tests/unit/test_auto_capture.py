"""Phase 0-2 TDD (updated for Phase 2-3): BUG-2 -- AutoCapture must be called

Original bug: ensure_future() dropped in environments with no running loop.
Current fix: MemoryCapturePlugin.aafter_agent() uses asyncio.create_task() instead.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class FakeAutoCapture:
    def __init__(self):
        self.call_count = 0

    async def process(self, user_input, result, scope=None):
        self.call_count += 1


@pytest.mark.asyncio
async def test_auto_capture_is_awaited():
    """BUG-2 fix: MemoryCapturePlugin.aafter_agent must schedule process via create_task."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from olav.plugins.middleware.memory_capture import MemoryCapturePlugin

    fake_store = MagicMock()
    fake_llm = MagicMock()
    plugin = MemoryCapturePlugin(store=fake_store, llm=fake_llm)

    msgs = [
        SystemMessage(content="be helpful"),
        HumanMessage(content="hello"),
        AIMessage(content="hi there"),
    ]
    state = {"messages": msgs}
    runtime = MagicMock()

    task_fired = []

    with patch("olav.core.memory.middleware.AutoCaptureMiddleware") as MockCapture:
        mock_instance = MockCapture.return_value
        mock_instance.process = AsyncMock(side_effect=lambda *a, **kw: task_fired.append(True))
        plugin._capture_mw = None

        await plugin.aafter_agent(state, runtime)
        await asyncio.sleep(0)

    assert len(task_fired) == 1, (
        f"AutoCaptureMiddleware.process was called {len(task_fired)} times. "
        "Expected exactly 1 (BUG-2: process was never awaited)."
    )


@pytest.mark.asyncio
async def test_auto_capture_timeout_is_non_fatal():
    """MemoryCapturePlugin.aafter_agent returns None; never propagates exceptions."""
    from langchain_core.messages import HumanMessage

    from olav.plugins.middleware.memory_capture import MemoryCapturePlugin

    plugin = MemoryCapturePlugin()
    state = {"messages": [HumanMessage(content="test")]}
    runtime = MagicMock()

    async def slow_process(*a, **kw):
        await asyncio.sleep(999)

    with patch("olav.core.memory.middleware.AutoCaptureMiddleware") as MockCapture:
        mock_instance = MockCapture.return_value
        mock_instance.process = slow_process
        plugin._capture_mw = None

        result = await plugin.aafter_agent(state, runtime)

    assert result is None, "aafter_agent must return None and not raise"

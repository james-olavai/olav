"""Gap-A TDD: callback plugins must be passed into graph.ainvoke config."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.anyio
async def test_ainvoke_passes_callbacks_to_graph():
    """graph.ainvoke must receive config['callbacks'] with the registered callback plugins."""
    from olav.agents.agent import OLAVAgent

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={"messages": []})

    fake_cb = MagicMock(name="fake_callback_plugin")

    with (
        patch.object(OLAVAgent, "__init__", lambda *a, **kw: None),
    ):
        agent = object.__new__(OLAVAgent)
        # Inject the bare minimum attrs
        agent.graph = mock_graph
        registry = MagicMock()
        registry.get_callback_plugins.return_value = [fake_cb]
        agent.plugin_registry = registry

        await agent.ainvoke("hello world", thread_id="t1")

    call_kwargs = mock_graph.ainvoke.call_args
    config = call_kwargs[1].get("config") or call_kwargs[0][1]
    assert "callbacks" in config, "ainvoke config must include 'callbacks' key"
    assert fake_cb in config["callbacks"], "Registered callback plugin must be in config callbacks"


@pytest.mark.anyio
async def test_ainvoke_no_callbacks_registered():
    """When no callback plugins are registered, callbacks list is empty (not missing)."""
    from olav.agents.agent import OLAVAgent

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={"messages": []})

    with patch.object(OLAVAgent, "__init__", lambda *a, **kw: None):
        agent = object.__new__(OLAVAgent)
        agent.graph = mock_graph
        registry = MagicMock()
        registry.get_callback_plugins.return_value = []
        agent.plugin_registry = registry

        await agent.ainvoke("hello", thread_id=None)

    config = mock_graph.ainvoke.call_args[1].get("config") or {}
    assert config.get("callbacks") == [], "Empty callback list must still be passed"

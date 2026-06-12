"""Phase 2-4 TDD: GuardrailsPlugin

Assert:
- Plugin is subclass of OLAVMiddlewarePlugin
- abefore_model() modifies system message with guardrail block when memories exist
- abefore_model() returns None when no guardrail memories found
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_guardrails_plugin_importable():
    from olav.plugins.middleware.guardrails import GuardrailsPlugin  # noqa: F401


def test_guardrails_plugin_is_middleware_subclass():
    from langchain.agents.middleware.types import AgentMiddleware

    from olav.plugins.middleware.guardrails import GuardrailsPlugin

    assert issubclass(GuardrailsPlugin, AgentMiddleware)


def test_guardrails_plugin_name():
    from olav.plugins.middleware.guardrails import GuardrailsPlugin

    assert GuardrailsPlugin.name == "guardrails"


async def test_abefore_model_injects_guardrails_into_system_message():
    """When guardrail memories exist, system message gets the constraint block appended."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langgraph.types import Overwrite

    from olav.plugins.middleware.guardrails import GuardrailsPlugin

    fake_store = MagicMock()
    plugin = GuardrailsPlugin(store=fake_store)

    system_content = "You are a helpful network assistant."
    system_msg = SystemMessage(content=system_content)
    human_msg = HumanMessage(content="show bgp summary on R3")
    state = {"messages": [system_msg, human_msg]}
    runtime = MagicMock()

    constraint_block = "\n\n=== LEARNED CONSTRAINTS ===\n  ⚠ R3 bgp timed out last time\n=== END ==="

    with patch(
        "olav.core.memory.guardrails.GuardrailInjector"
    ) as MockInjector:
        instance = MockInjector.return_value
        instance.inject.return_value = system_content + constraint_block

        result = await plugin.abefore_model(state, runtime)

    assert result is not None, "Should return state update when guardrails injected"
    assert isinstance(result["messages"], Overwrite), "Must use Overwrite to replace messages"
    updated = result["messages"].value
    # First message should be updated system message
    assert updated[0].content == system_content + constraint_block
    # Second message unchanged
    assert updated[1] is human_msg


async def test_abefore_model_returns_none_when_no_guardrails():
    """When inject() returns unchanged system prompt, return None."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from olav.plugins.middleware.guardrails import GuardrailsPlugin

    system_content = "You are a helpful network assistant."
    fake_store = MagicMock()
    plugin = GuardrailsPlugin(store=fake_store)

    state = {
        "messages": [SystemMessage(content=system_content), HumanMessage(content="hi")]
    }
    runtime = MagicMock()

    with patch("olav.core.memory.guardrails.GuardrailInjector") as MockInjector:
        instance = MockInjector.return_value
        # inject returns unchanged string
        instance.inject.return_value = system_content

        result = await plugin.abefore_model(state, runtime)

    assert result is None


async def test_abefore_model_returns_none_when_no_system_message():
    """When there's no system message in state, plugin returns None gracefully."""
    from langchain_core.messages import HumanMessage

    from olav.plugins.middleware.guardrails import GuardrailsPlugin

    plugin = GuardrailsPlugin()
    state = {"messages": [HumanMessage(content="hi")]}
    runtime = MagicMock()

    result = await plugin.abefore_model(state, runtime)
    assert result is None

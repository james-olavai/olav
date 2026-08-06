"""What we actually put on the wire, per provider — without an API key.

Asked whether the fields passed were tested against each provider's
requirements. They were not: the existing gate checks `inspect.signature`, which
answers "does this driver accept the kwarg" and nothing about the request that
results. Only deepseek and the local llama.cpp (as "openai") had ever been sent
a real request; the reported agent error 400 on Claude came from two fields
switched on for a provider nobody had exercised.

Signatures are the wrong layer for that question, but a live endpoint is not the
only alternative: every langchain chat model builds its payload locally via
`_get_request_payload`, so the exact JSON can be inspected offline. These tests
pin what each provider receives, so a change in a driver — or in OLAV's
determinism layer — shows up here rather than as a 400 in someone's terminal.

Coverage note, stated plainly: this is the *request* layer. It cannot tell you
whether a provider ACCEPTS the request — that still needs a real call, and only
two providers have had one (dev_docs/115 §12).
"""

from __future__ import annotations

import importlib

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from olav.core.llm import _DETERMINISM_DEFAULT_PROVIDERS, apply_tool_call_determinism


class _Args(BaseModel):
    x: str


_TOOL = StructuredTool.from_function(
    func=lambda **kw: kw, name="t", description="d", args_schema=_Args
)

# (provider, import path, ctor kwargs). Only drivers that build a payload
# offline; ones needing network at construction are skipped by the fixture.
_DRIVERS = [
    ("anthropic", "langchain_anthropic.ChatAnthropic", {"model": "claude-sonnet-4-5"}),
    ("openai", "langchain_openai.ChatOpenAI", {"model": "gpt-4o"}),
    ("deepseek", "langchain_deepseek.ChatDeepSeek", {"model": "deepseek-chat"}),
]


def _payload(path: str, ctor: dict, provider: str | None):
    mod, cls = path.rsplit(".", 1)
    try:
        klass = getattr(importlib.import_module(mod), cls)
    except ImportError:  # pragma: no cover - driver not installed
        pytest.skip(f"{mod} not installed")
    model = klass(api_key="x", **ctor)
    if provider is not None:
        model = apply_tool_call_determinism(model, provider)
    bound = model.bind_tools([_TOOL])
    build = getattr(bound.bound, "_get_request_payload", None)
    if build is None:  # pragma: no cover - driver shape changed
        pytest.skip(f"{cls} has no _get_request_payload")
    return build([HumanMessage(content="hi")], **bound.kwargs)


class TestAnthropicPayload:
    """The reported 400. Both fields are real Anthropic API features with
    version requirements, and OLAV had been adding them unasked."""

    def test_no_tool_choice_and_no_strict_field_by_default(self):
        p = _payload("langchain_anthropic.ChatAnthropic", {"model": "claude-sonnet-4-5"}, "anthropic")
        assert p.get("tool_choice") is None, (
            "OLAV must not inject tool_choice — it sent none before this feature"
        )
        assert "strict" not in p["tools"][0], (
            "a strict field on every tool definition is what we stopped sending"
        )
        assert sorted(p["tools"][0]) == ["description", "input_schema", "name"]

    def test_the_knobs_do_reach_the_payload_when_asked_for(self):
        """Proof this test can see the difference — otherwise the check above
        would pass even if the determinism layer were still applying them."""
        p = _payload("langchain_anthropic.ChatAnthropic", {"model": "claude-sonnet-4-5"}, None)
        mod = importlib.import_module("langchain_anthropic")
        model = mod.ChatAnthropic(api_key="x", model="claude-sonnet-4-5")
        bound = model.bind_tools([_TOOL], strict=True, parallel_tool_calls=False)
        p = bound.bound._get_request_payload(
            [HumanMessage(content="hi")], **bound.kwargs
        )
        assert p["tool_choice"] == {
            "type": "auto",
            "disable_parallel_tool_use": True,
        }
        assert p["tools"][0]["strict"] is True


class TestMeasuredProvidersStillSendTheKnobs:
    @pytest.mark.parametrize(
        "provider,path,ctor",
        [d for d in _DRIVERS if d[0] in _DETERMINISM_DEFAULT_PROVIDERS],
    )
    def test_strict_reaches_the_tool_schema(self, provider, path, ctor):
        p = _payload(path, ctor, provider)
        tools = p.get("tools") or []
        assert tools, f"{provider}: no tools in payload"
        fn = tools[0].get("function", tools[0])
        assert fn.get("strict") is True, (
            f"{provider} is in the default set but strict never reached the wire"
        )

    @pytest.mark.parametrize(
        "provider,path,ctor",
        [d for d in _DRIVERS if d[0] in _DETERMINISM_DEFAULT_PROVIDERS],
    )
    def test_parallel_tool_calls_reaches_the_payload(self, provider, path, ctor):
        p = _payload(path, ctor, provider)
        assert p.get("parallel_tool_calls") is False


class TestDefaultSetIsJustified:
    def test_every_defaulted_provider_has_a_payload_test_here(self):
        """Adding a provider to the default set without pinning its payload is
        how the Claude 400 happened."""
        covered = {d[0] for d in _DRIVERS}
        missing = sorted(_DETERMINISM_DEFAULT_PROVIDERS - covered)
        assert not missing, (
            f"defaulted on without a payload test: {missing}. Add it to _DRIVERS "
            "and assert what the provider receives."
        )

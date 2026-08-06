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
    ("openrouter", "langchain_openrouter.ChatOpenRouter", {"model": "openai/gpt-4o-mini"}),
    ("xai", "langchain_xai.ChatXAI", {"model": "grok-3-mini"}),
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
    inner = bound.bound

    build = getattr(inner, "_get_request_payload", None)
    if build is not None:
        return build([HumanMessage(content="hi")], **bound.kwargs)

    # ChatOpenRouter is not a BaseChatOpenAI subclass: it builds
    # `{**params, **kwargs}` from _create_message_dicts and then filters with
    # _strip_internal_kwargs before sending. Reproduce that, so the assertions
    # run instead of skipping — a skipped payload check guards nothing, which is
    # how openrouter first landed in the default set with no coverage at all.
    make = getattr(inner, "_create_message_dicts", None)
    if make is not None:
        _msgs, params = make([HumanMessage(content="hi")], None)
        payload = {**params, **bound.kwargs}
        strip = getattr(
            importlib.import_module(inner.__class__.__module__),
            "_strip_internal_kwargs",
            None,
        )
        if strip is not None:
            strip(payload)
        return payload

    raise AssertionError(  # pragma: no cover - a new driver shape
        f"{cls}: no way to build a payload offline. Add one rather than "
        "skipping — this file exists because unexercised requests reach users."
    )


class TestAnthropicPayload:
    """Anthropic encodes both knobs differently from everyone else, so pin the
    exact shape.

    History worth keeping: when a user reported agent error 400 on Claude, this
    class asserted the opposite — that OLAV must send NEITHER field — because the
    determinism layer had switched them on for a provider nobody had exercised,
    and that looked like the cause. Measurement against the live API disproved
    it: all 10 models the account can reach accept both. The 400 came from
    somewhere else (temperature > 1.0 is one confirmed Claude-specific 400).
    """

    def test_strict_becomes_a_field_on_the_tool_definition(self):
        p = _payload(
            "langchain_anthropic.ChatAnthropic", {"model": "claude-sonnet-4-5"}, "anthropic"
        )
        assert p["tools"][0]["strict"] is True, (
            "Anthropic takes strict per tool, not as a top-level request field"
        )

    def test_parallel_tool_calls_becomes_tool_choice_not_a_top_level_field(self):
        p = _payload(
            "langchain_anthropic.ChatAnthropic", {"model": "claude-sonnet-4-5"}, "anthropic"
        )
        assert "parallel_tool_calls" not in p
        assert p["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}

    def test_without_the_knobs_neither_appears(self):
        """Proof the assertions above can tell the difference — otherwise they
        would pass even if the determinism layer stopped applying."""
        import importlib

        mod = importlib.import_module("langchain_anthropic")
        model = mod.ChatAnthropic(api_key="x", model="claude-sonnet-4-5")
        bound = model.bind_tools([_TOOL])
        p = bound.bound._get_request_payload([HumanMessage(content="hi")], **bound.kwargs)
        assert p.get("tool_choice") is None
        assert "strict" not in p["tools"][0]


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
        """Each provider expresses "one call per turn" differently — assert the
        provider's own encoding, not a shared field name. Anthropic has no
        `parallel_tool_calls` key at all: the driver folds it into tool_choice as
        `disable_parallel_tool_use`, which is why a naive shared assertion here
        failed on it.
        """
        p = _payload(path, ctor, provider)
        if provider == "anthropic":
            assert p.get("tool_choice") == {
                "type": "auto",
                "disable_parallel_tool_use": True,
            }
        else:
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

    @pytest.mark.parametrize(
        "provider,path,ctor",
        [d for d in _DRIVERS if d[0] in _DETERMINISM_DEFAULT_PROVIDERS],
    )
    def test_the_payload_can_actually_be_built(self, provider, path, ctor):
        """Membership of _DRIVERS is not coverage — the assertion has to run.

        openrouter was added to the default set, listed here, and both of its
        payload checks silently skipped because ChatOpenRouter exposes no
        _get_request_payload. A skipped guard is indistinguishable from a passing
        one in the summary line.
        """
        payload = _payload(path, ctor, provider)
        assert isinstance(payload, dict) and payload, (
            f"{provider}: payload could not be built — the checks above would "
            "have skipped rather than failed"
        )

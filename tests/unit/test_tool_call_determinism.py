"""Function-call determinism defaults, per provider capability.

Tool-call *arg shape* is the dominant small-model failure mode in this codebase,
and CLAUDE.md is explicit that it must be fixed at the coercion layer rather
than with prompt imperatives: "prose rules change *whether* a small model calls
the tool, never *how correctly*". `strict` is that coercion moved to the
protocol — the provider validates against the JSON schema instead of the model
being asked nicely. `parallel_tool_calls=False` narrows the output space further,
and the orchestrator is a thin router to ONE sub-agent anyway.

Zero-LLM by construction: these assert the kwargs reaching `bind_tools`, not
model behaviour. Whether strict actually lowers the malformed-call rate is a
*behavioural* claim, and CLAUDE.md requires N>=3 runs for those
(tests/e2e/_variance.py:assert_success_rate) — deliberately not claimed here.
"""

from __future__ import annotations

import pytest

from olav.core.llm import _TOOL_CALL_KNOBS, apply_tool_call_determinism


class _FakeLLM:
    """Stands in for a chat model; records what bind_tools received."""

    def __init__(self) -> None:
        self.seen: dict | None = None

    def bind_tools(self, tools, **kwargs):
        self.seen = kwargs
        return self


@pytest.mark.parametrize("provider,expected", [
    ("deepseek",   {"strict": True, "parallel_tool_calls": False}),
    ("openai",     {"strict": True, "parallel_tool_calls": False}),
    ("xai",        {"strict": True, "parallel_tool_calls": False}),
    ("together",   {"strict": True, "parallel_tool_calls": False}),
    ("openrouter", {"strict": True, "parallel_tool_calls": False}),
    ("anthropic",  {"strict": True, "parallel_tool_calls": False}),
    ("perplexity", {"strict": True}),          # no parallel_tool_calls in its signature
    ("groq",       {}),                        # accepts neither
    ("mistralai",  {}),
    ("ollama",     {}),
    ("google_genai", {}),
])
def test_only_supported_knobs_are_passed(provider, expected):
    """Passing an unsupported kwarg is a TypeError at the first real tool call."""
    llm = _FakeLLM()
    apply_tool_call_determinism(llm, provider).bind_tools([])
    assert llm.seen == expected


def test_unknown_provider_is_left_alone():
    llm = _FakeLLM()
    apply_tool_call_determinism(llm, "some-new-vendor").bind_tools([])
    assert llm.seen == {}


def test_none_provider_is_left_alone():
    llm = _FakeLLM()
    apply_tool_call_determinism(llm, None).bind_tools([])
    assert llm.seen == {}


def test_explicit_caller_value_wins():
    """These are defaults, not overrides — a caller that means it keeps its value."""
    llm = _FakeLLM()
    apply_tool_call_determinism(llm, "deepseek").bind_tools(
        [], strict=False, parallel_tool_calls=True)
    assert llm.seen == {"strict": False, "parallel_tool_calls": True}


def test_env_opt_out(monkeypatch):
    """A provider that accepts strict but implements it badly needs an escape
    hatch that is not a code change — and an A/B run needs one to measure with."""
    monkeypatch.setenv("OLAV_TOOL_CALL_DETERMINISM", "0")
    llm = _FakeLLM()
    apply_tool_call_determinism(llm, "deepseek").bind_tools([])
    assert llm.seen == {}


def test_a_model_without_bind_tools_is_returned_untouched():
    class _NoTools:
        pass

    obj = _NoTools()
    assert apply_tool_call_determinism(obj, "deepseek") is obj


def test_every_knob_name_is_one_we_know_how_to_set():
    """Guards against a table entry the wrapper would silently ignore."""
    settable = {"strict", "parallel_tool_calls"}
    for provider, knobs in _TOOL_CALL_KNOBS.items():
        unknown = knobs - settable
        assert not unknown, f"{provider} declares knobs the wrapper cannot set: {unknown}"

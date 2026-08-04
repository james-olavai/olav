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


class _RedispatchingLLM:
    """Mimics ChatDeepSeek's beta-endpoint switch, the shape that recursed.

    `ChatDeepSeek.bind_tools(strict=True)` does
    `model_copy(update={"api_base": BETA})` and re-dispatches to the copy; the
    recursion terminates because the copy's api_base is no longer the default.
    `model_copy` carries instance attributes, so the copy's `bind_tools` was the
    determinism wrapper, whose closure called the ORIGINAL instance — still on the
    default api_base. Every hop re-entered the beta branch: RecursionError.

    _FakeLLM above cannot express this, which is exactly why 17 passing unit
    tests said nothing while the feature was broken on the one provider it was
    written for. Found by an actual DeepSeek call.
    """

    DEFAULT = "https://api.example.com"
    BETA = "https://api.example.com/beta"

    def __init__(self, api_base: str | None = None) -> None:
        self.api_base = api_base or self.DEFAULT
        self.seen: dict | None = None
        self.hops = 0

    def model_copy(self, update: dict):
        clone = _RedispatchingLLM(update.get("api_base"))
        # The behaviour that caused the bug: instance attributes come along.
        for k, v in self.__dict__.items():
            if k not in {"api_base"}:
                clone.__dict__[k] = v
        return clone

    def bind_tools(self, tools, **kwargs):
        self.hops += 1
        if self.hops > 10:
            raise AssertionError("re-dispatch loop — the wrapper leaked into the copy")
        if kwargs.get("strict") is True and self.api_base == self.DEFAULT:
            return self.model_copy({"api_base": self.BETA}).bind_tools(tools, **kwargs)
        self.seen = kwargs
        return self


def test_beta_endpoint_redispatch_does_not_recurse():
    llm = _RedispatchingLLM()
    bound = apply_tool_call_determinism(llm, "deepseek").bind_tools([])
    # Landed on the beta instance, with the knobs intact.
    assert bound.api_base == _RedispatchingLLM.BETA
    assert bound.seen == {"strict": True, "parallel_tool_calls": False}


def test_the_patch_is_restored_after_a_redispatching_call():
    """Detaching during the call must not permanently remove the defaults."""
    llm = _RedispatchingLLM()
    patched = apply_tool_call_determinism(llm, "deepseek")
    patched.bind_tools([])
    llm.hops = 0
    second = patched.bind_tools([])
    assert second.seen == {"strict": True, "parallel_tool_calls": False}, (
        "second bind lost the defaults — the wrapper was not restored"
    )

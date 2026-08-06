"""Does each provider ACCEPT the request we send? One real call, opt-in.

The layer nothing covered. `test_llm_provider_drivers` checks the driver's
signature; `test_provider_request_payload` checks the JSON we build. Neither can
tell you whether the vendor's API accepts it — and that gap is exactly where the
reported agent error 400 on Claude lived: two tool-call fields were switched on
for a provider that had never been sent a request.

Skipped unless the provider's key is in the environment, so a missing key never
reddens CI. Each provider costs one minimal call: a one-line prompt and a
two-field tool.

    ANTHROPIC_API_KEY=...  uv run pytest tests/e2e/test_provider_endpoint_smoke.py -v

What each case asserts:
  1. the request is accepted at all (no 4xx — this is what a 400 would catch)
  2. a tool call comes back with arguments that validate against the schema
  3. separately, whether the provider tolerates OLAV's determinism knobs, which
     is what decides if it may join _DETERMINISM_DEFAULT_PROVIDERS
"""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

pytestmark = pytest.mark.e2e


class _Peer(BaseModel):
    """Deliberately not flat: nested + typed is where arg-shape errors show."""

    ip: str = Field(description="peer IP address")
    asn: int = Field(description="autonomous system number")


class _ChangeArgs(BaseModel):
    device: str = Field(description="device hostname")
    peer: _Peer
    action: str = Field(description="one of: add, remove")


_TOOL = StructuredTool.from_function(
    func=lambda **kw: kw,
    name="plan_bgp_change",
    description="Draft a BGP peering change for one device.",
    args_schema=_ChangeArgs,
)

_PROMPT = (
    "Draft a BGP change on device r1.example: add a peer at 10.0.0.1 in AS 65001. "
    "Use the tool."
)

# (provider, env var, model, ctor extras). Model choices are the cheapest
# tool-calling model each vendor offers at time of writing.
_CASES = [
    ("anthropic", "ANTHROPIC_API_KEY", "claude-sonnet-4-5", {}),
    ("openai", "OPENAI_API_KEY", "gpt-4o-mini", {}),
    ("openrouter", "OPENROUTER_API_KEY", "openai/gpt-4o-mini", {}),
    ("google_genai", "GOOGLE_API_KEY", "gemini-2.5-flash", {}),
    ("groq", "GROQ_API_KEY", "llama-3.3-70b-versatile", {}),
    ("xai", "XAI_API_KEY", "grok-3-mini", {}),
    ("together", "TOGETHER_API_KEY", "meta-llama/Llama-3.3-70B-Instruct-Turbo", {}),
    ("perplexity", "PERPLEXITY_API_KEY", "sonar", {}),
    ("deepseek", "DEEPSEEK_API_KEY", "deepseek-chat", {}),
]


def _model(provider: str, env: str, model: str, extras: dict):
    key = os.environ.get(env) or os.environ.get(env.lower())
    if not key:
        pytest.skip(f"{env} not set — paste it into .env to enable this provider")
    from langchain.chat_models import init_chat_model

    return init_chat_model(model, model_provider=provider, api_key=key, **extras)


@pytest.mark.parametrize("provider,env,model,extras", _CASES, ids=[c[0] for c in _CASES])
def test_provider_accepts_a_plain_tool_call(provider, env, model, extras):
    """No determinism knobs — the baseline every provider must pass."""
    llm = _model(provider, env, model, extras)
    resp = llm.bind_tools([_TOOL]).invoke([HumanMessage(content=_PROMPT)])

    calls = getattr(resp, "tool_calls", None) or []
    assert calls, f"{provider}: no tool call returned"
    _ChangeArgs.model_validate(calls[0]["args"])


@pytest.mark.parametrize("provider,env,model,extras", _CASES, ids=[c[0] for c in _CASES])
def test_provider_tolerates_the_determinism_knobs(provider, env, model, extras):
    """The question that decides membership of _DETERMINISM_DEFAULT_PROVIDERS.

    A failure here is a *result*, not a bug in this file: it means the provider
    rejects what OLAV's determinism layer would add, and the provider must stay
    out of the default set. Record the outcome in llm.py rather than muting it.
    """
    from olav.core.llm import _TOOL_CALL_KNOBS

    knobs = _TOOL_CALL_KNOBS.get(provider) or frozenset()
    if not knobs:
        pytest.skip(f"{provider} accepts no determinism knobs")

    llm = _model(provider, env, model, extras)
    kwargs = {}
    if "strict" in knobs:
        kwargs["strict"] = True
    if "parallel_tool_calls" in knobs:
        kwargs["parallel_tool_calls"] = False

    try:
        resp = llm.bind_tools([_TOOL], **kwargs).invoke([HumanMessage(content=_PROMPT)])
    except Exception as exc:  # noqa: BLE001 — the outcome we are measuring
        pytest.fail(
            f"{provider} rejected {kwargs}: {type(exc).__name__}: {exc}\n"
            f"→ keep {provider!r} out of _DETERMINISM_DEFAULT_PROVIDERS"
        )

    calls = getattr(resp, "tool_calls", None) or []
    assert calls, f"{provider}: knobs accepted but no tool call returned"
    _ChangeArgs.model_validate(calls[0]["args"])

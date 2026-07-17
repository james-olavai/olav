"""Per-provider thinking-mode dispatch (llm.py).

`thinking_mode` maps to a DIFFERENT request-shape per backend — the whole
point of the hybrid-thinking design (orchestrator reasons, sub-agents run
fast) only works if the OFF/ON switch reaches each provider through the
mechanism that provider actually honours:

* local llama.cpp / qwen / gemma → ``chat_template_kwargs.enable_thinking``
* Ollama                          → ``reasoning`` (bool)
* DeepSeek hosted API             → ``thinking: {"type": ...}``
* OpenRouter / Google             → neither (excluded — they reject or
  forward the local kwarg to a downstream that chokes)

The DeepSeek branch is the one under test here: api.deepseek.com IGNORES
both ``chat_template_kwargs.enable_thinking`` and ``reasoning_effort``, so
before this dispatch OLAV's OFF switch was a no-op there (verified live
2026-07-17). These tests capture the params ``get_chat_model`` builds — no
network.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def captured_params(monkeypatch):
    """Capture the params LLMFactory.get_chat_model passes to init_chat_model."""
    from olav.core import llm as llm_mod

    calls: list[dict] = []

    def _fake(**params):
        calls.append(params)
        return object()

    monkeypatch.setattr(llm_mod, "init_chat_model", _fake)
    monkeypatch.setattr(
        "olav.core.llm_instrumentation.TokenUsageCallback",
        lambda *a, **kw: None,
    )
    return calls


def _build(captured, base_url, thinking_mode):
    from olav.core.llm import LLMFactory

    LLMFactory.get_chat_model(
        model_name="stub", base_url=base_url, thinking_mode=thinking_mode
    )
    assert captured, "init_chat_model stub never called"
    return captured[-1]


def _extra_body(params):
    # get_chat_model hoists model_kwargs.extra_body to a top-level extra_body
    # param (langchain-openai's preferred shape) before calling init_chat_model,
    # so merge both places.
    merged = dict((params.get("model_kwargs") or {}).get("extra_body") or {})
    merged.update(params.get("extra_body") or {})
    return merged


# ── DeepSeek: the Anthropic-style `thinking` toggle ─────────────────────────

DEEPSEEK = "https://api.deepseek.com/v1"


def test_deepseek_enabled_sends_thinking_type_enabled(captured_params):
    eb = _extra_body(_build(captured_params, DEEPSEEK, "enabled"))
    assert eb.get("thinking") == {"type": "enabled"}


def test_deepseek_disabled_sends_thinking_type_disabled(captured_params):
    eb = _extra_body(_build(captured_params, DEEPSEEK, "disabled"))
    assert eb.get("thinking") == {"type": "disabled"}


def test_deepseek_never_uses_the_noop_chat_template_kwargs(captured_params):
    """DeepSeek must NOT get chat_template_kwargs.enable_thinking — it
    ignores it, which is exactly the bug this branch fixes."""
    for mode in ("enabled", "disabled"):
        eb = _extra_body(_build(captured_params, DEEPSEEK, mode))
        assert "chat_template_kwargs" not in eb, (
            f"deepseek {mode} wrongly used the no-op chat_template_kwargs path"
        )


# ── Local llama-server path is unchanged (regression guard) ──────────────────

LOCAL = "http://localhost:8080/v1"


def test_local_enabled_still_uses_chat_template_kwargs(captured_params):
    eb = _extra_body(_build(captured_params, LOCAL, "enabled"))
    ctk = eb.get("chat_template_kwargs") or {}
    assert ctk.get("enable_thinking") is True
    assert "thinking" not in eb  # not the deepseek shape


def test_local_disabled_still_uses_chat_template_kwargs(captured_params):
    eb = _extra_body(_build(captured_params, LOCAL, "disabled"))
    ctk = eb.get("chat_template_kwargs") or {}
    assert ctk.get("enable_thinking") is False


# ── OpenRouter (incl. deepseek-via-openrouter) stays excluded ────────────────

def test_openrouter_deepseek_does_not_get_thinking_param(captured_params):
    """DeepSeek *via OpenRouter* is a different path — OpenRouter has its own
    reasoning field and forwarding the raw toggle downstream broke tool
    calls (see llm.py comment). The direct-endpoint branch must not fire."""
    eb = _extra_body(_build(captured_params, "https://openrouter.ai/api/v1", "disabled"))
    assert "thinking" not in eb
    assert "chat_template_kwargs" not in eb

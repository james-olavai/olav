"""ARCH-19 #B — ``LLMFactory`` forwards backend-specific prompt-cache hints.

The hints are attached at ``init_chat_model`` time based on a
case-insensitive substring match on the configured ``base_url``. Matching
backends:

* ``vllm`` in URL  → ``extra_body.enable_prefix_caching = True``
* ``llama.cpp`` or ``:8080`` → ``cache_prompt = True``
* ``ollama`` or ``:11434`` → ``keep_alive = "5m"``

Non-matching backends (OpenAI, OpenRouter, Groq, Anthropic, …) must NOT
receive any of these keys so we don't poison remote APIs with spurious
params. ``OLAV_LOCAL_CACHE_DISABLE=1`` is the operator escape hatch.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def captured_params(monkeypatch):
    """Replace ``init_chat_model`` with a capturer; return the last params dict."""
    from olav.core import llm as llm_mod

    calls: list[dict] = []

    def _fake(**params):
        calls.append(params)
        # Return a dummy that is_truthy so LLMFactory.get_chat_model
        # doesn't swallow "None" as an error.
        return object()

    monkeypatch.setattr(llm_mod, "init_chat_model", _fake)
    # Disable TokenUsageCallback so the captured params stay focused.
    monkeypatch.setattr(
        "olav.core.llm_instrumentation.TokenUsageCallback",
        lambda *a, **kw: None,
    )
    return calls


@pytest.fixture
def clean_disable(monkeypatch):
    monkeypatch.delenv("OLAV_LOCAL_CACHE_DISABLE", raising=False)
    yield monkeypatch


def _call(base_url: str):
    """Invoke LLMFactory.get_chat_model with a given ``base_url`` override."""
    from olav.core.llm import LLMFactory

    LLMFactory.get_chat_model(model_name="stub-model")
    # Force the captured params to include our base_url by re-calling
    # with an override — the factory merges kwargs into params, so
    # ``base_url=...`` lands in the captured dict.


# ── vLLM ---------------------------------------------------------------------


def test_vllm_hint_added_for_vllm_backend(captured_params, clean_disable, monkeypatch):
    from olav.core.llm import LLMFactory

    LLMFactory.get_chat_model(model_name="m", base_url="http://vllm-host:8000/v1")
    assert captured_params, "init_chat_model stub never called"
    params = captured_params[-1]
    # extra_body is promoted to top-level by llm.py to suppress LangChain UserWarning.
    extra_body = params.get("extra_body") or (params.get("model_kwargs") or {}).get("extra_body") or {}
    assert extra_body.get("enable_prefix_caching") is True


# ── llama.cpp ---------------------------------------------------------------


def test_llama_cpp_hint_added(captured_params, clean_disable):
    from olav.core.llm import LLMFactory

    LLMFactory.get_chat_model(model_name="m", base_url="http://127.0.0.1:8080/v1")
    params = captured_params[-1]
    assert (params.get("model_kwargs") or {}).get("cache_prompt") is True


# ── Ollama -------------------------------------------------------------------


def test_ollama_hint_added(captured_params, clean_disable):
    from olav.core.llm import LLMFactory

    LLMFactory.get_chat_model(model_name="m", base_url="http://localhost:11434/v1")
    params = captured_params[-1]
    # extra_body is promoted to top-level by llm.py to suppress LangChain UserWarning.
    extra_body = params.get("extra_body") or (params.get("model_kwargs") or {}).get("extra_body") or {}
    assert extra_body.get("keep_alive") == "5m"


# ── Remote APIs must NOT receive local hints ---------------------------------


@pytest.mark.parametrize(
    "base_url",
    [
        "https://openrouter.ai/api/v1",
        "https://api.openai.com/v1",
        "https://api.anthropic.com/v1",
        "https://api.groq.com/openai/v1",
    ],
)
def test_remote_api_receives_no_local_cache_hint(base_url, captured_params, clean_disable):
    from olav.core.llm import LLMFactory

    LLMFactory.get_chat_model(model_name="m", base_url=base_url)
    params = captured_params[-1]
    mkw = params.get("model_kwargs") or {}
    # None of the three local hints should appear.
    assert "cache_prompt" not in mkw
    assert "keep_alive" not in mkw
    extra_body = mkw.get("extra_body") or {}
    assert "enable_prefix_caching" not in extra_body


# ── Escape hatch -------------------------------------------------------------


def test_env_disable_suppresses_all_hints(captured_params, monkeypatch):
    monkeypatch.setenv("OLAV_LOCAL_CACHE_DISABLE", "1")
    from olav.core.llm import LLMFactory

    LLMFactory.get_chat_model(model_name="m", base_url="http://127.0.0.1:11434")
    params = captured_params[-1]
    mkw = params.get("model_kwargs") or {}
    assert "keep_alive" not in mkw
    assert "cache_prompt" not in mkw
    extra_body = mkw.get("extra_body") or {}
    assert "enable_prefix_caching" not in extra_body

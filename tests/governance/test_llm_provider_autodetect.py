"""LLMFactory auto-detects model_provider from base_url (T2 run-8 → run-10 fix).

Background
----------

LangChain's ``init_chat_model`` cannot infer a provider from custom model
names like ``"x-ai/grok-4.1-fast"`` (the model string OpenRouter returns
for xAI models). Without an explicit ``model_provider`` it raises
``ValueError: Unable to infer model provider`` at every agent construction
— which cascades into the entire CLI path (``olav --agent ops ...``)
returning a bare traceback instead of an agent response.

The config schema already supports an explicit ``llm.model_provider``
field, but minimally-generated configs (``olav init`` with no dev
template) and env-only bootstrap paths leave it empty. LLMFactory now
falls back to a base_url → provider map covering the OpenAI-compatible
aggregators we see in the wild.

This pin keeps that map honest across refactors.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
LLM_PY = REPO / "src" / "olav" / "core" / "llm.py"


def _read_llm_source() -> str:
    return LLM_PY.read_text(encoding="utf-8")


def test_llm_factory_has_base_url_provider_fallback():
    """``get_chat_model`` must auto-detect the provider from ``base_url``
    when ``llm_config.model_provider`` is empty."""
    src = _read_llm_source()
    assert "Auto-detect provider from base_url" in src, (
        "LLMFactory dropped the base_url → provider fallback; "
        "langchain init_chat_model will fail on 'x-ai/grok-4.1-fast'."
    )


def test_llm_factory_covers_openrouter():
    """OpenRouter is the primary aggregator used in T2 integration."""
    src = _read_llm_source()
    assert re.search(r'"openrouter"\s+in\s+_url', src), (
        "LLMFactory fallback no longer recognises OpenRouter base_url."
    )
    # Accept either assignment shape. This asserted only
    # `params["model_provider"] = "openrouter"` and broke when the block was
    # refactored (2026-08-04) to stage the value in `_inferred` first, so a
    # driver-availability check could downgrade to the generic OpenAI-compatible
    # client instead of letting init_chat_model raise ImportError. The guarantee
    # under test is "openrouter is recognised and selected", not how the line is
    # spelled.
    assert re.search(
        r'(?:params\["model_provider"\]|_inferred)\s*=\s*"openrouter"', src), (
        "LLMFactory does not select model_provider='openrouter' when detected."
    )


def test_llm_factory_covers_additional_aggregators():
    """At minimum the fallback covers: together, groq, deepseek, perplexity."""
    src = _read_llm_source()
    for provider in ("together", "groq", "deepseek", "perplexity"):
        assert f'"{provider}"' in src, (
            f"LLMFactory base_url fallback dropped {provider}; "
            "extend it or remove this pin with an ADR."
        )

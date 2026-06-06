"""LLM config smoke: current api.json must be initializable without API calls.

Catches the class of bug where api.json specifies a provider whose langchain
package is not installed — e.g. base_url=api.deepseek.com auto-detects to
model_provider=deepseek which requires langchain-deepseek (not installed),
causing ImportError at agent startup.

Gate: the two live tests are skipped when no api_key is configured, so push
CI (which has no credentials) is not affected.  The static test always runs.
"""
from __future__ import annotations

import importlib

import pytest


# ---------------------------------------------------------------------------
# 1. Static: auto-detection table covers deepseek via OpenAI-compat path
# ---------------------------------------------------------------------------

def test_deepseek_url_can_be_routed_as_openai():
    """api.deepseek.com can be used with model_provider=openai (OpenAI-compat).

    The auto-detection in LLMFactory maps api.deepseek.com → model_provider=deepseek
    which requires langchain-deepseek.  Providing an explicit model_provider=openai
    in api.json bypasses this and uses ChatOpenAI instead — no extra package needed.

    This test pins that the explicit-override path in LLMFactory is present so a
    future refactor cannot silently remove it and reintroduce the ImportError.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "src" / "olav" / "core" / "llm.py").read_text()
    # Explicit model_provider beats auto-detection
    assert "_model_provider = overrides.get(\"model_provider\") or llm_config.model_provider" in src, (
        "LLMFactory no longer reads explicit model_provider from config; "
        "api.deepseek.com with model_provider=openai would fall through to "
        "auto-detect=deepseek and require langchain-deepseek."
    )
    # Auto-detect for deepseek URLs is still there (to document the risk)
    assert '"deepseek" in _url' in src, (
        "Auto-detect table no longer has a deepseek branch — update this test "
        "if the detection table was intentionally removed."
    )


# ---------------------------------------------------------------------------
# 2. Live: resolved config initialises a ChatModel without an API call
# ---------------------------------------------------------------------------

def _get_llm_cfg():
    from olav.core.config import get_llm_config
    return get_llm_config()


_HAS_KEY = bool(_get_llm_cfg().api_key)
_SKIP_NO_KEY = pytest.mark.skipif(
    not _HAS_KEY,
    reason="LLM not configured (no api_key) — set llm.api_key in api.json or OLAV_LLM_API_KEY",
)


@_SKIP_NO_KEY
def test_llm_config_provider_package_installed():
    """The langchain package for the resolved model_provider must be importable.

    Catches: model_provider=deepseek without langchain-deepseek installed, or
    model_provider=anthropic without langchain-anthropic, etc.
    """
    cfg = _get_llm_cfg()
    provider = cfg.model_provider or "openai"

    # Map known providers to their langchain package
    _PROVIDER_PKG = {
        "openai":    "langchain_openai",
        "anthropic": "langchain_anthropic",
        "deepseek":  "langchain_deepseek",
        "ollama":    "langchain_ollama",
        "groq":      "langchain_groq",
        "together":  "langchain_together",
        "openrouter": "langchain_openai",   # OpenRouter uses ChatOpenAI
        "perplexity": "langchain_openai",   # Perplexity uses ChatOpenAI
    }
    pkg = _PROVIDER_PKG.get(provider, f"langchain_{provider}")
    try:
        importlib.import_module(pkg)
    except ImportError:
        pytest.fail(
            f"model_provider={provider!r} requires {pkg} but it is not installed.\n"
            f"  Fix A: pip install {pkg}\n"
            f"  Fix B: set llm.model_provider=openai in api.json to use ChatOpenAI "
            f"(works for any OpenAI-compatible endpoint including api.deepseek.com)"
        )


@_SKIP_NO_KEY
def test_llm_config_chat_model_initialises():
    """LLMFactory.get_chat_model() must not raise with the current api.json config.

    This exercises the full initialisation path (provider detection, package import,
    model object construction) without making a network call.  A failure here means
    every agent startup would fail at the same point.
    """
    from olav.core.llm import LLMFactory
    try:
        model = LLMFactory.get_chat_model()
    except ImportError as exc:
        pytest.fail(
            f"ChatModel initialisation raised ImportError — missing langchain package:\n{exc}\n\n"
            "Most likely cause: auto-detected model_provider requires a package that is not "
            "installed.  Add llm.model_provider=openai to api.json to use ChatOpenAI for any "
            "OpenAI-compatible endpoint (DeepSeek, OpenRouter, Together, etc.)."
        )
    except Exception as exc:
        pytest.fail(f"ChatModel initialisation raised unexpected error: {type(exc).__name__}: {exc}")

    assert model is not None

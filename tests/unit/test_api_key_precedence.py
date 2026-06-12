"""Pin the per-section-first / shared-second / env-third api_key precedence.

Heterogeneous multi-provider configs (e.g. LLM on OpenRouter,
embedding on Perplexity) require per-section api_key to override
shared.api_key.  Before 2026-05-01 the precedence was reversed —
shared would clobber per-section.  This test guards against
re-flipping that without intent.
"""
from __future__ import annotations

import json

import pytest


def _write_api_json(tmp_path, payload: dict):
    cfg_dir = tmp_path / ".olav" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "api.json").write_text(json.dumps(payload))
    return tmp_path


def _load_with_cwd(tmp_path, monkeypatch):
    """Point ConfigLoader at the tmp_path config dir + reload singleton.

    _CONFIG_DIR is a module-level constant frozen at import time, so
    cwd changes alone don't redirect file reads — patch it explicitly.
    Also drop ambient key env vars: the env tier outranks file config,
    so a leaked OLAV_LLM_API_KEY from an earlier test (or a dev shell)
    would silently win every precedence assertion below.
    """
    for var in ("OLAV_LLM_API_KEY", "OLAV_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    import olav.core.config as cfgmod
    monkeypatch.setattr(cfgmod, "_CONFIG_DIR", tmp_path / ".olav" / "config")
    cfgmod.reload_config()
    return cfgmod


# ─── LLM ──────────────────────────────────────────────────────────────────


def test_llm_per_section_key_beats_shared(tmp_path, monkeypatch):
    """When llm.api_key is set, shared.api_key MUST NOT override it."""
    _write_api_json(tmp_path, {
        "shared": {"api_key": "shared-XXX"},
        "llm": {"api_key": "llm-OPENROUTER", "provider": "custom",
                "base_url": "https://x", "model": "m"},
        "embedding": {"mode": "api"},
    })
    cfgmod = _load_with_cwd(tmp_path, monkeypatch)
    assert cfgmod.get_llm_config().api_key == "llm-OPENROUTER"


def test_llm_falls_back_to_shared_when_per_section_empty(tmp_path, monkeypatch):
    """When llm.api_key is missing/empty, shared.api_key kicks in."""
    _write_api_json(tmp_path, {
        "shared": {"api_key": "shared-default"},
        "llm": {"provider": "custom", "base_url": "https://x", "model": "m"},
        "embedding": {"mode": "api"},
    })
    cfgmod = _load_with_cwd(tmp_path, monkeypatch)
    assert cfgmod.get_llm_config().api_key == "shared-default"


def test_llm_falls_back_to_env_when_neither_set(tmp_path, monkeypatch):
    """No shared, no llm — OPENAI_API_KEY env wins."""
    _write_api_json(tmp_path, {
        "llm": {"provider": "openai", "model": "m"},
        "embedding": {"mode": "api"},
    })
    cfgmod = _load_with_cwd(tmp_path, monkeypatch)
    # set AFTER the helper: _load_with_cwd clears ambient key env vars,
    # and this test deliberately exercises the env-fallback tier.
    monkeypatch.setenv("OPENAI_API_KEY", "env-fallback")
    cfgmod.reload_config()
    assert cfgmod.get_llm_config().api_key == "env-fallback"


# ─── Embedding ─────────────────────────────────────────────────────────────


def test_embedding_per_section_key_beats_shared(tmp_path, monkeypatch):
    """embedding.api.api_key MUST override shared.api_key."""
    _write_api_json(tmp_path, {
        "shared": {"api_key": "shared-XXX"},
        "llm": {"provider": "openai", "model": "m"},
        "embedding": {
            "mode": "api",
            "api": {"api_key": "pplx-EMBED", "model": "x", "base_url": "y"},
        },
    })
    cfgmod = _load_with_cwd(tmp_path, monkeypatch)
    assert cfgmod.get_embedding_config().openai_api_key == "pplx-EMBED"


def test_embedding_falls_back_to_shared_when_per_section_empty(tmp_path, monkeypatch):
    """No embedding.api.api_key → shared.api_key picked up."""
    _write_api_json(tmp_path, {
        "shared": {"api_key": "shared-default"},
        "llm": {"provider": "openai", "model": "m"},
        "embedding": {"mode": "api", "api": {"model": "x", "base_url": "y"}},
    })
    cfgmod = _load_with_cwd(tmp_path, monkeypatch)
    assert cfgmod.get_embedding_config().openai_api_key == "shared-default"


# ─── Heterogeneous multi-provider scenario ────────────────────────────────


def test_heterogeneous_keys_dont_collide(tmp_path, monkeypatch):
    """The motivating use case: OpenRouter LLM + Perplexity embedding.

    Each service must read ITS OWN per-section key — no cross-talk.
    """
    _write_api_json(tmp_path, {
        # No shared.api_key — heterogeneous setup
        "llm": {
            "provider": "custom",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "google/gemma-4-31b-it:free",
            "api_key": "sk-or-v1-OPENROUTER",
        },
        "embedding": {
            "mode": "api",
            "api": {
                "model": "pplx-embed-v1-0.6b",
                "base_url": "https://api.perplexity.ai/v1",
                "api_key": "pplx-PERPLEXITY",
            },
        },
    })
    cfgmod = _load_with_cwd(tmp_path, monkeypatch)
    assert cfgmod.get_llm_config().api_key == "sk-or-v1-OPENROUTER"
    assert cfgmod.get_embedding_config().openai_api_key == "pplx-PERPLEXITY"

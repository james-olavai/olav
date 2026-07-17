"""Sprint 0b: ``LLMConfig.model_tier`` resolves per config / env / heuristic.

The tier classification is constitutional for ARCH-16/17/18/19 — every
downstream small-model optimisation keys off this string. The resolution
contract is intentionally narrow:

    1. ``OLAV_LLM_MODEL_TIER`` env var
    2. Explicit ``llm.model_tier`` in api.json / llm.json
    3. Regex inference from the ``llm.model`` string
    4. Conservative ``"large"`` fallback
"""

from __future__ import annotations

import os

import pytest

from olav.core.config import ModelTier, TIER_DEFAULTS, tier_default


@pytest.fixture
def clean_env(monkeypatch):
    """Strip the env-var override so heuristics can drive the test."""
    monkeypatch.delenv("OLAV_LLM_MODEL_TIER", raising=False)
    yield monkeypatch


class _FakeLoader:
    """Stand-in ConfigLoader that bypasses the real .olav/config/ tree."""

    _shared: dict[str, object] = {}

    def _env_override(self, section, key, default):
        env_key = f"OLAV_{section.upper()}_{key.upper()}"
        value = os.environ.get(env_key)
        return value if value is not None else default


def _mk_llm(model: str, *, tier: str | None = None):
    from olav.core.config import LLMConfig

    data: dict[str, object] = {"model": model}
    if tier is not None:
        data["model_tier"] = tier
    return LLMConfig(data, _FakeLoader())


# ── enum + defaults -----------------------------------------------------------


def test_model_tier_enum_has_three_members():
    assert {m.value for m in ModelTier} == {"small", "medium", "large"}


def test_tier_defaults_cover_every_member():
    for member in ModelTier:
        assert member.value in TIER_DEFAULTS
        for key in ("recall_top_k", "return_compact_chars", "static_context_mode"):
            assert key in TIER_DEFAULTS[member.value], (
                f"tier {member.value} missing key {key}"
            )


def test_tier_default_falls_back_on_unknown():
    assert tier_default("mythical", "recall_top_k", 99) == 99
    assert tier_default("small", "does_not_exist", "fb") == "fb"
    assert tier_default("small", "recall_top_k", 99) == 1


# ── resolution precedence ----------------------------------------------------


def test_explicit_config_wins(clean_env):
    cfg = _mk_llm("gemma-7b", tier="large")  # regex would say small
    assert cfg.model_tier == "large"


def test_env_override_wins_over_config(clean_env):
    clean_env.setenv("OLAV_LLM_MODEL_TIER", "medium")
    cfg = _mk_llm("claude-opus-4-5", tier="large")
    assert cfg.model_tier == "medium"


def test_regex_infers_small(clean_env):
    for name in ("gemma-7b", "llama-3.1-8b-instruct", "phi-3-mini", "qwen2-4b"):
        assert _mk_llm(name).model_tier == "small", name


def test_regex_infers_medium(clean_env):
    for name in ("llama-3-13b", "qwen2-32b", "mixtral-8x7b"):
        assert _mk_llm(name).model_tier == "medium", name


def test_sized_family_names_classify_by_parameter_count(clean_env):
    """Regression: family+size names must key off the SIZE, not fall through.

    ``gemma4-31b-it-qat`` used to hit the ``large`` fallback because the old
    ``\\bgemma\\b`` alternative couldn't match "gemma4" (no word boundary
    before the digit) and no size pattern covered 31b — so a 31B local model
    got a 200K budget + loose caps. It is a 10–34B model → medium.
    """
    for name in ("gemma4-31b-it-qat", "gemma4-31b-it", "gemma3-27b", "qwen3-30b"):
        assert _mk_llm(name).model_tier == "medium", name
    # small gemmas still classify small by their size
    for name in ("gemma4-9b", "gemma-2b", "gemma3:9b"):
        assert _mk_llm(name).model_tier == "small", name


def test_regex_conservative_fallback_for_unknown(clean_env):
    # Claude / GPT-4 names never match the small/medium regexes —
    # these should fall through to "large".
    for name in ("claude-opus-4-7", "gpt-4o", "gpt-4-turbo", ""):
        assert _mk_llm(name).model_tier == "large", name


def test_env_override_rejects_case(clean_env):
    # Lowercase the env value so downstream string compares are stable.
    clean_env.setenv("OLAV_LLM_MODEL_TIER", "SMALL")
    cfg = _mk_llm("gpt-4-turbo")
    assert cfg.model_tier == "small"

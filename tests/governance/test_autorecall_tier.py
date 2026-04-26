"""ARCH-18 #3: AutoRecall top_k follows the active model_tier.

Per-tier defaults live in ``olav.core.config.TIER_DEFAULTS``. The
middleware resolves ``top_k`` lazily via ``_resolve_top_k`` so tests and
callers can swap tier between constructions.
"""

from __future__ import annotations

import pytest


def test_resolve_top_k_uses_tier_defaults(monkeypatch):
    from olav.core.memory import middleware as mw

    class _Store:
        pass

    recall = mw.AutoRecallMiddleware(store=_Store())

    # Small tier → 1
    class _Cfg:
        model_tier = "small"

    monkeypatch.setattr(mw, "__name__", mw.__name__)  # no-op guard
    monkeypatch.setattr(
        "olav.core.config.get_llm_config",
        lambda: _Cfg(),
    )
    assert recall._resolve_top_k() == 1

    _Cfg.model_tier = "medium"
    assert recall._resolve_top_k() == 2

    _Cfg.model_tier = "large"
    # R83.4 follow-up: large-tier recall_top_k bumped 3 → 8 to give the
    # diversifier headroom for cross-platform schema/value entries.
    # Phase 1 (dev_docs/61): bumped 8 → 13 to fit the usage_guide quota
    # alongside schema (5) + value (5) + usage_guide (3) = 13.
    assert recall._resolve_top_k() == 13


def test_resolve_top_k_explicit_overrides_tier(monkeypatch):
    from olav.core.memory import middleware as mw

    class _Cfg:
        model_tier = "small"

    monkeypatch.setattr("olav.core.config.get_llm_config", lambda: _Cfg())

    # Explicit override sticks regardless of the (small) tier default.
    explicit = mw.AutoRecallMiddleware(store=None, top_k=7)
    assert explicit._resolve_top_k() == 7


def test_resolve_top_k_falls_back_on_config_error(monkeypatch):
    from olav.core.memory import middleware as mw

    def boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr("olav.core.config.get_llm_config", boom)
    recall = mw.AutoRecallMiddleware(store=None)
    # Should fall back to RECALL_TOP_K (3) without raising.
    assert recall._resolve_top_k() == 3

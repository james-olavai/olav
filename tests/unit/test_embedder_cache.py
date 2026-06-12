"""Tests for the in-process embedding cache in olav.core.embedder.

Without this cache, multi-step agent flows re-embed the same user
message 5-7× per chapter (orchestrator + sub-agents + tool decisions
all run AutoRecallMiddleware.abefore_model). Demo7 Ch6 traces showed
3+ embed_text calls per single ``olav --agent ...`` invocation. The
cache turns repeats into 1 real call + N memory hits.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from olav.core.embedder import (
    _cache_get,
    _cache_put,
    clear_embed_cache,
    embed_text,
    get_embed_cache_stats,
)


@pytest.fixture(autouse=True)
def _reset():
    clear_embed_cache()
    yield
    clear_embed_cache()


def test_cache_get_miss_returns_none():
    assert _cache_get("never seen") is None
    assert get_embed_cache_stats()["misses"] == 1
    assert get_embed_cache_stats()["hits"] == 0


def test_cache_put_then_get_returns_vector():
    vec = [0.1, 0.2, 0.3]
    _cache_put("hello", vec)
    assert _cache_get("hello") == vec
    assert get_embed_cache_stats()["hits"] == 1


def test_cache_lru_eviction(monkeypatch):
    """When at capacity, oldest entries evict first."""
    monkeypatch.setattr("olav.core.embedder._EMBED_CACHE_MAX", 3)
    _cache_put("a", [1.0])
    _cache_put("b", [2.0])
    _cache_put("c", [3.0])
    assert get_embed_cache_stats()["size"] == 3
    _cache_put("d", [4.0])  # evicts 'a'
    assert _cache_get("a") is None  # evicted
    assert _cache_get("d") == [4.0]


def test_cache_lru_recency_promotes(monkeypatch):
    """Hits move keys to most-recently-used; not the next eviction."""
    monkeypatch.setattr("olav.core.embedder._EMBED_CACHE_MAX", 3)
    _cache_put("a", [1.0])
    _cache_put("b", [2.0])
    _cache_put("c", [3.0])
    _cache_get("a")  # 'a' now most recent
    _cache_put("d", [4.0])  # should evict 'b' (oldest), not 'a'
    assert _cache_get("a") == [1.0]
    assert _cache_get("b") is None


def test_cache_disabled_with_zero_size(monkeypatch):
    """OLAV_EMBED_CACHE_SIZE=0 → fully disabled, every call misses."""
    monkeypatch.setattr("olav.core.embedder._EMBED_CACHE_MAX", 0)
    _cache_put("x", [1.0])
    # _cache_put is a no-op when max <= 0
    assert _cache_get("x") is None


def test_embed_text_uses_cache():
    """embed_text() consults the cache before calling the backend."""
    fake_vec = [0.5] * 768
    call_count = {"n": 0}

    class FakeClient:
        class embeddings:
            @staticmethod
            def create(input, model, encoding_format=None, **kwargs):
                call_count["n"] += 1
                class _R:
                    data = [type("d", (), {"embedding": fake_vec})()]
                return _R

    with patch("olav.core.embedder._get_api_client") as gac, \
         patch("olav.core.config.get_embedding_config") as gec:
        gac.return_value = (FakeClient, "test-model")
        gec.return_value = type("c", (), {"mode": "api"})()
        # 3 calls with same text → 1 backend hit, 2 cache hits
        for _ in range(3):
            v = embed_text("hello world")
            assert v == fake_vec
        assert call_count["n"] == 1
        stats = get_embed_cache_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1


def test_embed_text_empty_string_returns_none_no_cache():
    """Empty input is rejected before cache."""
    assert embed_text("") is None
    assert get_embed_cache_stats()["size"] == 0


def test_embed_text_caches_per_unique_text():
    """Different texts get separate cache entries."""
    fake_vec = [0.5] * 768
    call_count = {"n": 0}

    class FakeClient:
        class embeddings:
            @staticmethod
            def create(input, model, encoding_format=None, **kwargs):
                call_count["n"] += 1
                class _R:
                    data = [type("d", (), {"embedding": [float(call_count["n"])]})()]
                return _R

    with patch("olav.core.embedder._get_api_client") as gac, \
         patch("olav.core.config.get_embedding_config") as gec:
        gac.return_value = (FakeClient, "test-model")
        gec.return_value = type("c", (), {"mode": "api"})()
        v1 = embed_text("query A")
        v2 = embed_text("query B")
        v1b = embed_text("query A")
        assert v1 == [1.0]
        assert v2 == [2.0]
        assert v1b == v1
        assert call_count["n"] == 2  # two unique texts → 2 backend hits
        assert get_embed_cache_stats()["hits"] == 1


def test_embed_text_failure_does_not_cache_none():
    """If backend raises, embed_text returns None and does NOT cache it
    so a transient failure can recover on retry."""

    class FailingClient:
        class embeddings:
            @staticmethod
            def create(input, model):
                raise RuntimeError("backend down")

    with patch("olav.core.embedder._get_api_client") as gac, \
         patch("olav.core.config.get_embedding_config") as gec:
        gac.return_value = (FailingClient, "test-model")
        gec.return_value = type("c", (), {"mode": "api"})()
        assert embed_text("transient fail") is None
        # No entry cached → retry can succeed later
        assert get_embed_cache_stats()["size"] == 0


def test_clear_embed_cache_resets_stats():
    _cache_put("x", [1.0])
    _cache_get("x")
    assert get_embed_cache_stats()["hits"] == 1
    clear_embed_cache()
    stats = get_embed_cache_stats()
    assert stats == {"hits": 0, "misses": 0, "size": 0}

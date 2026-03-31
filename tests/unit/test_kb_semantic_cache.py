"""Phase 5-2: KnowledgeBase SemanticCache integration test.

Verifies that:
1. KnowledgeBase has a _cache attribute (SemanticCache)
2. The cache uses KB_CACHE_TABLE (not the global CACHE_TABLE)
3. search() calls _cache.get() before running vector search (cache check)
4. search() calls _cache.put() after a cache miss to store results
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_kb(store=None):
    from olav.core.knowledge import KnowledgeBase

    if store is None:
        store = MagicMock()
        store.embedding_dim = 384
        store.table_exists.return_value = False

    return KnowledgeBase(store=store, embedding_dim=384)


def test_kb_has_cache_attribute():
    """KnowledgeBase must expose a ._cache attribute that is a SemanticCache."""
    from olav.core.memory import SemanticCache

    kb = _make_kb()
    assert hasattr(kb, "_cache"), "KnowledgeBase must have a ._cache attribute"
    assert isinstance(kb._cache, SemanticCache), (
        f"._cache must be SemanticCache, got {type(kb._cache)}"
    )


def test_kb_cache_uses_kb_cache_table():
    """._cache must use KB_CACHE_TABLE, not the global CACHE_TABLE."""
    from olav.core.knowledge import KB_CACHE_TABLE
    from olav.core.memory import CACHE_TABLE

    kb = _make_kb()
    assert kb._cache._table_name == KB_CACHE_TABLE, (
        f"KB cache must use table '{KB_CACHE_TABLE}', got '{kb._cache._table_name}'"
    )
    assert kb._cache._table_name != CACHE_TABLE, (
        "KB cache must NOT share the global memory CACHE_TABLE"
    )


def test_kb_search_checks_cache_first():
    """search() must call _cache.get() before running vector search."""
    kb = _make_kb()

    # Patch _embed to return a deterministic vector
    kb._embed = MagicMock(return_value=[0.1] * 384)

    # Patch cache to return a cached result
    expected = [{"text": "cached chunk", "score": 0.99}]
    kb._cache = MagicMock()
    kb._cache.get.return_value = expected

    # Patch store.table_exists to True so search doesn't bail early
    kb._store.table_exists.return_value = True

    result = kb.search("network topology", limit=5)

    kb._cache.get.assert_called_once(), "cache.get() must be called on every search"
    assert result == expected[:5], f"Must return cached results, got {result}"
    # store search methods should NOT be called on cache hit
    kb._store.search_by_vector.assert_not_called()
    kb._store.search_by_text.assert_not_called()


def test_kb_search_stores_results_on_cache_miss():
    """On a cache miss, search() must call _cache.put() with the results."""
    kb = _make_kb()
    kb._embed = MagicMock(return_value=[0.2] * 384)

    mock_results = [{"text": "fresh chunk", "score": 0.8}]

    # cache.get returns None (miss)
    kb._cache = MagicMock()
    kb._cache.get.return_value = None

    # store returns results
    kb._store.table_exists.return_value = True
    kb._store.search_by_vector.return_value = mock_results
    kb._store.search_by_text.return_value = []

    with patch("olav.core.knowledge.rrf_fusion", return_value=mock_results):
        result = kb.search("show interfaces", limit=5)

    kb._cache.put.assert_called_once(), "cache.put() must be called after a cache miss"
    assert result == mock_results[:5]

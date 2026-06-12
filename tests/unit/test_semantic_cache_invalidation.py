def test_semantic_cache_invalidate_all_clears_entries(tmp_path):
    """put entries, invalidate, verify they're gone."""
    from olav.core.memory import LanceDBStore, SemanticCache

    db_path = tmp_path / "test_memory.lance"
    store = LanceDBStore(db_path=db_path, embedding_dim=4)
    cache = SemanticCache(store)

    vector = [0.1, 0.2, 0.3, 0.4]
    results = [{"id": "doc1", "text": "hello"}]
    cache.put(vector, results)

    hit = cache.get(vector)
    assert hit == results

    cache.invalidate_all()

    hit_after = cache.get(vector)
    assert hit_after is None


def test_semantic_cache_invalidate_all_on_empty(tmp_path):
    """safe to call when no entries exist — no crash, stays empty."""
    from olav.core.memory import SemanticCache

    cache = SemanticCache(threshold=0.02)
    # In-memory cache starts empty (after any previous test cleanup)
    SemanticCache._entries.clear()
    assert len(SemanticCache._entries) == 0

    cache.invalidate_all()  # must not raise

    assert len(SemanticCache._entries) == 0


def test_semantic_cache_invalidate_all_allows_repopulation(tmp_path):
    """after invalidation, new entries can be stored and retrieved."""
    from olav.core.memory import SemanticCache

    cache = SemanticCache(threshold=0.02)
    SemanticCache._entries.clear()

    vector1 = [0.1, 0.1, 0.1, 0.1]
    cache.put(vector1, [{"id": "1"}])
    cache.invalidate_all()

    assert len(SemanticCache._entries) == 0

    vector2 = [0.2, 0.2, 0.2, 0.2]
    results2 = [{"id": "2"}]
    cache.put(vector2, results2)

    hit = cache.get(vector2)
    assert hit == results2

    assert len(SemanticCache._entries) > 0

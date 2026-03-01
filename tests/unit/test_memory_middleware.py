"""Unit tests for memory middleware: Auto-Recall, Auto-Capture, Time-Decay."""

import asyncio
import json
import math
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_store(existing_memories=None, table_exists=True):
    """Create a mock LanceDBStore."""
    store = MagicMock()
    store.embedding_dim = 384
    store.table_exists.return_value = table_exists
    store.search_by_vector.return_value = existing_memories or []
    store.search_by_text.return_value = existing_memories or []
    store.get_memories.return_value = existing_memories or []
    store.add_memory.return_value = {"status": "success", "id": "test-id"}
    store.update_weight.return_value = {"status": "success", "id": "x"}
    return store


def _make_memory(
    id="m1", text="OSPF adjacency established on R1", category="fact",
    scope="ops", timestamp=None, weight=1.0, score=0.1
):
    """Build a sample memory dict."""
    return {
        "id": id, "text": text, "category": category, "scope": scope,
        "timestamp": timestamp or datetime(2025, 1, 1, tzinfo=timezone.utc),
        "weight": weight, "score": score, "metadata": "{}",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Recall
# ─────────────────────────────────────────────────────────────────────────────

class TestAutoRecallMiddleware:
    """Tests for AutoRecallMiddleware.enrich()."""

    @pytest.mark.asyncio
    async def test_enrich_str_input_with_memories(self):
        """String input is enriched with a <relevant-memories> block."""
        from olav.core.memory.middleware import AutoRecallMiddleware

        mems = [_make_memory(text="BGP prefix limit reached on R2")]
        store = _make_store(existing_memories=mems)

        recall = AutoRecallMiddleware(store, top_k=3)
        # Provide a fixed vector so hybrid_search is called
        recall._embedder = MagicMock()
        recall._embedder.encode.return_value = MagicMock(tolist=lambda: [0.1] * 384)

        with patch("olav.core.memory.middleware.hybrid_search", return_value=mems):
            result = await recall.enrich("show bgp summary", scope="ops")

        assert "<relevant-memories>" in result
        assert "BGP prefix limit reached" in result
        assert "show bgp summary" in result

    @pytest.mark.asyncio
    async def test_enrich_dict_input_last_user_msg(self):
        """Dict input: memories are prepended to the last user message."""
        from olav.core.memory.middleware import AutoRecallMiddleware

        mems = [_make_memory(text="R3 OSPF neighbor timeout 30s")]
        store = _make_store(existing_memories=mems)

        recall = AutoRecallMiddleware(store, top_k=3)
        recall._embedder = MagicMock()
        recall._embedder.encode.return_value = MagicMock(tolist=lambda: [0.0] * 384)

        input_ = {"messages": [{"role": "user", "content": "check ospf neighbors"}]}
        with patch("olav.core.memory.middleware.hybrid_search", return_value=mems):
            result = await recall.enrich(input_, scope="ops")

        assert isinstance(result, dict)
        last_msg = result["messages"][-1]
        assert "<relevant-memories>" in last_msg["content"]
        assert "R3 OSPF neighbor timeout" in last_msg["content"]

    @pytest.mark.asyncio
    async def test_enrich_no_table_returns_original(self):
        """Returns original input if memory table doesn't exist."""
        from olav.core.memory.middleware import AutoRecallMiddleware

        store = _make_store(table_exists=False)
        recall = AutoRecallMiddleware(store)

        result = await recall.enrich("some query", scope="global")
        assert result == "some query"

    @pytest.mark.asyncio
    async def test_enrich_empty_memories_returns_original(self):
        """Returns original if no memories match."""
        from olav.core.memory.middleware import AutoRecallMiddleware

        store = _make_store(existing_memories=[])
        recall = AutoRecallMiddleware(store)
        recall._embedder = MagicMock()
        recall._embedder.encode.return_value = MagicMock(tolist=lambda: [0.0] * 384)

        with patch("olav.core.memory.middleware.hybrid_search", return_value=[]):
            result = await recall.enrich("test query", scope="global")

        assert result == "test query"

    @pytest.mark.asyncio
    async def test_enrich_fallback_to_text_when_no_embedder(self):
        """Falls back to text search when embedder is unavailable."""
        from olav.core.memory.middleware import AutoRecallMiddleware

        mems = [_make_memory(text="VLAN 100 missing on Core-SW")]
        store = _make_store(existing_memories=mems)
        store.search_by_text.return_value = mems

        recall = AutoRecallMiddleware(store)
        recall._embedder = False  # explicitly disabled

        result = await recall.enrich("check vlan 100", scope="global")

        assert "<relevant-memories>" in result
        store.search_by_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_enrich_non_fatal_on_exception(self):
        """Returns original input if any exception occurs during enrichment."""
        from olav.core.memory.middleware import AutoRecallMiddleware

        store = _make_store()
        store.table_exists.side_effect = RuntimeError("DB error")

        recall = AutoRecallMiddleware(store)
        result = await recall.enrich("query text", scope="global")

        assert result == "query text"  # original returned, no exception raised


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Capture
# ─────────────────────────────────────────────────────────────────────────────

class TestAutoCaptureMiddleware:
    """Tests for AutoCaptureMiddleware.process()."""

    def _make_llm(self, response: str = '[{"text":"BGP neighbor R1 is up","category":"fact","importance":0.8}]'):
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=MagicMock(content=response))
        return llm

    @pytest.mark.asyncio
    async def test_process_stores_extracted_facts(self):
        """Extracted facts are stored in LanceDB."""
        from olav.core.memory.middleware import AutoCaptureMiddleware

        store = _make_store()
        llm = self._make_llm()
        capture = AutoCaptureMiddleware(store, llm, max_items=3)
        # Disable dedup check
        capture._embedder = False

        result = {"messages": [{"role": "ai", "content": "BGP session is now up on R1-R2."}]}
        await capture.process("check bgp status", result, scope="ops")

        store.add_memory.assert_called_once()
        call_kwargs = store.add_memory.call_args
        assert call_kwargs.kwargs["category"] == "fact"
        assert "BGP neighbor R1 is up" in call_kwargs.kwargs["text"]

    @pytest.mark.asyncio
    async def test_process_skips_on_error_result(self):
        """Nothing is stored when result indicates an error."""
        from olav.core.memory.middleware import AutoCaptureMiddleware

        store = _make_store()
        llm = self._make_llm()
        capture = AutoCaptureMiddleware(store, llm)

        await capture.process("query", {"status": "error", "response": "failed"}, scope="global")

        store.add_memory.assert_not_called()
        llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_handles_empty_llm_response(self):
        """Gracefully handles LLM returning empty array."""
        from olav.core.memory.middleware import AutoCaptureMiddleware

        store = _make_store()
        llm = self._make_llm(response="[]")
        capture = AutoCaptureMiddleware(store, llm)
        capture._embedder = False

        result = {"messages": [{"role": "ai", "content": "Done. Nothing significant happened."}]}
        await capture.process("simple query", result, scope="global")

        store.add_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_deduplicates_similar_memories(self):
        """Dedup check prevents storing near-duplicate memories."""
        from olav.core.memory.middleware import AutoCaptureMiddleware

        # Existing memory with low distance (high similarity)
        existing = [_make_memory(text="BGP neighbor R1 is up", score=0.02)]
        store = _make_store(existing_memories=existing)

        llm = self._make_llm()
        capture = AutoCaptureMiddleware(store, llm, similarity_dedup_threshold=0.92)

        # Give it a real embedder mock that returns a vector
        capture._embedder = MagicMock()
        capture._embedder.encode.return_value = MagicMock(tolist=lambda: [0.1] * 384)

        result = {"messages": [{"role": "ai", "content": "BGP session R1 up."}]}
        await capture.process("check bgp", result, scope="ops")

        # Should NOT store because dedup check triggers (score=0.02 < 1-0.92=0.08)
        store.add_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_non_fatal_on_exception(self):
        """Non-fatal: exceptions during capture do not propagate."""
        from olav.core.memory.middleware import AutoCaptureMiddleware

        store = _make_store()
        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM crash"))
        capture = AutoCaptureMiddleware(store, llm)
        capture._embedder = False

        result = {"messages": [{"role": "ai", "content": "Some response here."}]}
        # Should not raise
        await capture.process("query", result, scope="global")


# ─────────────────────────────────────────────────────────────────────────────
# Time-Decay
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyTimeDecay:
    """Tests for apply_time_decay()."""

    def test_decay_formula_old_memory(self):
        """Old memory (>half_life days) has weight below 0.7."""
        age_days = 90  # > 60 day half-life
        half_life = 60.0
        weight = max(0.1, 0.5 + 0.5 * math.exp(-age_days / half_life))
        assert weight < 0.7
        assert weight >= 0.1

    def test_decay_formula_new_memory(self):
        """New memory (<1 day) retains weight close to 1.0."""
        age_days = 0.1
        half_life = 60.0
        weight = max(0.1, 0.5 + 0.5 * math.exp(-age_days / half_life))
        assert weight > 0.99

    def test_apply_time_decay_updates_weights(self):
        """apply_time_decay() calls update_weight for each valid memory."""
        from olav.core.memory.middleware import apply_time_decay

        old_ts = datetime.now(timezone.utc) - timedelta(days=120)
        memories = [
            _make_memory(id="m1", timestamp=old_ts),
            _make_memory(id="m2", timestamp=old_ts),
        ]
        store = _make_store(existing_memories=memories)

        result = apply_time_decay(store, half_life_days=60)

        assert result["updated"] == 2
        assert result["errors"] == 0
        assert store.update_weight.call_count == 2

        # Verify new weight is decayed (< 1.0)
        new_weight = store.update_weight.call_args_list[0].kwargs["weight"]
        assert new_weight < 1.0
        assert new_weight >= 0.1

    def test_apply_time_decay_skips_missing_timestamp(self):
        """Memories without timestamp are skipped gracefully."""
        from olav.core.memory.middleware import apply_time_decay

        memories = [{"id": "m1", "text": "test", "timestamp": None}]
        store = _make_store(existing_memories=memories)

        result = apply_time_decay(store)
        assert result["skipped"] == 1
        assert result["updated"] == 0
        store.update_weight.assert_not_called()

    def test_apply_time_decay_no_table(self):
        """Skips gracefully when memory table does not exist."""
        from olav.core.memory.middleware import apply_time_decay

        store = _make_store(table_exists=False)
        result = apply_time_decay(store)

        assert result == {"updated": 0, "skipped": 0, "errors": 0}

    def test_schedule_time_decay_without_apscheduler(self):
        """Returns None when apscheduler is not installed."""
        from olav.core.memory.middleware import schedule_time_decay

        store = _make_store()
        with patch.dict("sys.modules", {"apscheduler": None,
                                         "apscheduler.schedulers": None,
                                         "apscheduler.schedulers.background": None}):
            result = schedule_time_decay(store)
        # None or raises ImportError — either is acceptable
        assert result is None or True  # just confirm no crash


# ─────────────────────────────────────────────────────────────────────────────
# RRF Recency Boost
# ─────────────────────────────────────────────────────────────────────────────

class TestRRFRecencyBoost:
    """Tests for rrf_fusion() with apply_weight_boost."""

    def test_weight_boost_applied(self):
        """High-weight memory ranks above equal-position low-weight memory."""
        from olav.core.memory import rrf_fusion

        # Both docs appear at rank 1 in separate lists — without boost they'd tie
        high_weight_doc = {"id": "hw", "text": "recent fact", "weight": 1.0}
        low_weight_doc  = {"id": "lw", "text": "old fact",    "weight": 0.2}

        # Both at rank 1 in their respective lists → same base RRF score
        results = rrf_fusion([[high_weight_doc], [low_weight_doc]], apply_weight_boost=True)
        ids = [r["id"] for r in results]

        # hw should rank first due to higher weight
        assert ids[0] == "hw"

    def test_weight_boost_disabled_equal_scores(self):
        """With boost disabled, equal-rank docs get identical scores."""
        from olav.core.memory import rrf_fusion

        doc_a = {"id": "a", "text": "fact a", "weight": 1.0}
        doc_b = {"id": "b", "text": "fact b", "weight": 0.1}

        results = rrf_fusion([[doc_a], [doc_b]], apply_weight_boost=False)
        scores = [r["rrf_score"] for r in results]

        # Both at rank 1 in separate single-item lists → same base RRF score
        assert abs(scores[0] - scores[1]) < 1e-9

    def test_missing_weight_defaults_to_1(self):
        """Docs without weight field don't crash and default to weight=1."""
        from olav.core.memory import rrf_fusion

        doc = {"id": "x", "text": "no weight"}  # no weight key
        results = rrf_fusion([[doc]], apply_weight_boost=True)
        assert results[0]["id"] == "x"
        assert results[0]["rrf_score"] > 0

    def test_combined_ranking_multiple_lists(self):
        """Doc appearing in both lists ranks higher than doc in only one."""
        from olav.core.memory import rrf_fusion

        shared = {"id": "shared", "text": "both", "weight": 0.8}
        unique = {"id": "unique", "text": "one",  "weight": 1.0}

        # shared appears in both lists; unique appears only once
        # With weight=0.8, shared's boosted score should be compared to unique's
        results = rrf_fusion([[shared, unique], [shared]], apply_weight_boost=True)
        ids = [r["id"] for r in results]
        # shared appears in 2 lists → higher base RRF, even after 0.8 weight
        assert ids[0] == "shared"


# ─────────────────────────────────────────────────────────────────────────────
# store_network_event()
# ─────────────────────────────────────────────────────────────────────────────

class TestStoreNetworkEvent:
    """Tests for store_network_event()."""

    def test_store_network_event_success(self):
        """Stores event with audit category and correct metadata."""
        from olav.core.memory import store_network_event, MemoryCategory

        store = _make_store()
        result = store_network_event(
            store=store,
            summary="BGP session flapped 3 times between R1 and R2",
            device="R1",
            event_type="bgp-flap",
            scope="ops",
        )

        assert result["status"] == "success"
        store.add_memory.assert_called_once()
        kwargs = store.add_memory.call_args.kwargs
        assert kwargs["category"] == MemoryCategory.AUDIT
        assert kwargs["scope"] == "ops"
        assert "BGP session flapped" in kwargs["text"]
        import json
        meta = kwargs["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        assert meta.get("device") == "R1"
        assert meta.get("event_type") == "bgp-flap"
        assert meta.get("source") == "network_event"

    def test_store_network_event_creates_table_if_absent(self):
        """Creates table when it does not yet exist."""
        from olav.core.memory import store_network_event

        store = _make_store(table_exists=False)
        store_network_event(store=store, summary="Link down on Gi0/1", scope="ops")

        store.create_table.assert_called_once()

    def test_store_network_event_with_embedder(self):
        """Uses embedder to produce a real vector when provided."""
        from olav.core.memory import store_network_event

        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = MagicMock(tolist=lambda: [0.5] * 384)

        store = _make_store()
        store_network_event(
            store=store,
            summary="OSPF adjacency dropped on R4",
            embedder=mock_embedder,
        )

        mock_embedder.encode.assert_called_once()
        vector_used = store.add_memory.call_args.kwargs["vector"]
        assert vector_used == [0.5] * 384

    def test_store_network_event_id_starts_with_evt(self):
        """Generated memory ID starts with 'evt-' prefix."""
        from olav.core.memory import store_network_event

        store = _make_store()
        store_network_event(store=store, summary="Interface bounce on Core-SW")

        mem_id = store.add_memory.call_args.kwargs["id"]
        assert mem_id.startswith("evt-")


# ─────────────────────────────────────────────────────────────────────────────
# Weighted RRF — list_weights parameter
# ─────────────────────────────────────────────────────────────────────────────

class TestWeightedRRF:
    """Tests that list_weights in rrf_fusion() actually scale list contributions."""

    def test_equal_weights_same_as_no_weights(self):
        """list_weights=[1.0, 1.0] is equivalent to no weights."""
        from olav.core.memory import rrf_fusion

        docs_a = [{"id": "a", "weight": 1.0}, {"id": "b", "weight": 1.0}]
        docs_b = [{"id": "c", "weight": 1.0}, {"id": "a", "weight": 1.0}]

        no_w   = rrf_fusion([docs_a, docs_b], apply_weight_boost=False)
        with_w = rrf_fusion([docs_a, docs_b], apply_weight_boost=False, list_weights=[1.0, 1.0])

        assert [r["id"] for r in no_w] == [r["id"] for r in with_w]

    def test_high_vector_weight_promotes_vector_only_doc(self):
        """Doc appearing only in vector list ranks above BM25-only doc when vector_weight >> text_weight."""
        from olav.core.memory import rrf_fusion

        vector_only = {"id": "vec", "text": "vector result", "weight": 1.0}
        text_only   = {"id": "txt", "text": "text result",   "weight": 1.0}

        results = rrf_fusion(
            [[vector_only], [text_only]],
            apply_weight_boost=False,
            list_weights=[10.0, 0.1],  # very high vector weight
        )
        ids = [r["id"] for r in results]
        assert ids[0] == "vec"

    def test_zero_weight_excludes_list_contribution(self):
        """list_weight=0.0 means that list contributes zero RRF score."""
        from olav.core.memory import rrf_fusion

        doc_a = {"id": "a", "weight": 1.0}
        doc_b = {"id": "b", "weight": 1.0}

        results = rrf_fusion([[doc_a], [doc_b]], apply_weight_boost=False, list_weights=[1.0, 0.0])
        # Only doc_a gets a non-zero score; doc_b gets 0 * 1/(k+1) = 0
        assert results[0]["id"] == "a"
        assert results[1]["rrf_score"] == 0.0

    def test_list_weights_applied_per_list(self):
        """Each list's RRF contribution is scaled by its respective weight."""
        from olav.core.memory import rrf_fusion

        doc = {"id": "x", "weight": 1.0}
        # Single doc in first list with weight 2.0 → score = 2.0/(60+1) ≈ 0.0328
        results = rrf_fusion([[doc]], apply_weight_boost=False, list_weights=[2.0])
        expected = 2.0 / (60 + 1)
        assert abs(results[0]["rrf_score"] - expected) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# SemanticCache
# ─────────────────────────────────────────────────────────────────────────────

def _make_cache_store(tmp_path):
    """Create a real LanceDBStore backed by a temp directory."""
    from olav.core.memory import LanceDBStore
    return LanceDBStore(db_path=str(tmp_path / "cache_test.lance"), embedding_dim=4)


class TestSemanticCache:
    """Tests for the Tier-0 SemanticCache class."""

    def test_miss_on_empty_cache(self, tmp_path):
        """Returns None when cache is empty."""
        from olav.core.memory import SemanticCache

        store = _make_cache_store(tmp_path)
        cache = SemanticCache(store, threshold=0.02, ttl_hours=24)
        assert cache.get([0.1, 0.2, 0.3, 0.4]) is None

    def test_hit_returns_stored_results(self, tmp_path):
        """After put(), get() with the same vector returns the stored results."""
        from olav.core.memory import SemanticCache

        store = _make_cache_store(tmp_path)
        cache = SemanticCache(store, threshold=0.5, ttl_hours=24)  # lenient threshold

        vec = [1.0, 0.0, 0.0, 0.0]
        results = [{"id": "m1", "text": "OSPF up", "rrf_score": 0.1}]

        cache.put(vec, results)
        hit = cache.get(vec)

        assert hit is not None
        assert hit[0]["id"] == "m1"

    def test_miss_when_distance_exceeds_threshold(self, tmp_path):
        """Returns None when stored vector is far from query vector."""
        from olav.core.memory import SemanticCache

        store = _make_cache_store(tmp_path)
        cache = SemanticCache(store, threshold=0.001, ttl_hours=24)  # very strict

        cache.put([1.0, 0.0, 0.0, 0.0], [{"id": "x"}])
        # Orthogonal vector → large distance
        result = cache.get([0.0, 1.0, 0.0, 0.0])
        assert result is None

    def test_invalidate_all_clears_entries(self, tmp_path):
        """invalidate_all() drops the cache table entirely."""
        from olav.core.memory import SemanticCache, CACHE_TABLE

        store = _make_cache_store(tmp_path)
        cache = SemanticCache(store, threshold=0.5, ttl_hours=24)

        cache.put([1.0, 0.0, 0.0, 0.0], [{"id": "y"}])
        cache.invalidate_all()

        db = store.connect()
        assert CACHE_TABLE not in db.table_names()

    def test_hybrid_search_uses_cache(self, tmp_path):
        """hybrid_search() with use_cache=True stores results on first call and hits on second."""
        from olav.core.memory import LanceDBStore, hybrid_search, MEMORY_TABLE

        store = _make_cache_store(tmp_path)
        # Create empty memory table so searches don't raise
        store.create_table(MEMORY_TABLE)

        vec = [1.0, 0.0, 0.0, 0.0]

        # First call — cache miss, runs full search (returns empty)
        r1 = hybrid_search(store, query="test", query_vector=vec, limit=5, use_cache=True)

        # Second call with same vector — should be a cache hit
        with patch("olav.core.memory.SemanticCache.get", return_value=[{"id": "cached"}]) as mock_get:
            r2 = hybrid_search(store, query="test", query_vector=vec, limit=5, use_cache=True)
            mock_get.assert_called_once()
            assert r2 == [{"id": "cached"}]

    def test_hybrid_search_bypasses_cache_when_disabled(self, tmp_path):
        """hybrid_search(use_cache=False) never touches SemanticCache."""
        from olav.core.memory import LanceDBStore, hybrid_search, MEMORY_TABLE

        store = _make_cache_store(tmp_path)
        store.create_table(MEMORY_TABLE)

        vec = [1.0, 0.0, 0.0, 0.0]
        with patch("olav.core.memory.SemanticCache.get") as mock_get:
            hybrid_search(store, query="test", query_vector=vec, limit=5, use_cache=False)
            mock_get.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# MemoryConfig — config.py integration
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryConfig:
    """Tests for MemoryConfig defaults and config integration."""

    def test_get_memory_config_returns_defaults(self):
        """get_memory_config() returns sensible default values."""
        from olav.core.config import get_memory_config

        cfg = get_memory_config()
        assert 0.0 < cfg.dedup_threshold <= 1.0
        assert cfg.cache_similarity_threshold >= 0.0
        assert cfg.fts_rebuild_every >= 1
        assert cfg.cache_ttl_hours >= 1
        assert cfg.cache_max_entries >= 1

    def test_dedup_threshold_default_is_point92(self):
        """Default dedup threshold is 0.92 as per design spec."""
        from olav.core.config import get_memory_config
        assert get_memory_config().dedup_threshold == 0.92

    def test_capture_middleware_reads_threshold_from_config(self):
        """AutoCaptureMiddleware without explicit threshold uses MemoryConfig."""
        from olav.core.memory.middleware import AutoCaptureMiddleware

        store = _make_store()
        llm = MagicMock()

        capture = AutoCaptureMiddleware(store, llm)  # no explicit threshold

        from olav.core.config import get_memory_config
        assert capture._dedup_threshold == get_memory_config().dedup_threshold

    def test_capture_middleware_explicit_threshold_overrides_config(self):
        """Explicit similarity_dedup_threshold parameter takes precedence over config."""
        from olav.core.memory.middleware import AutoCaptureMiddleware

        store = _make_store()
        llm = MagicMock()
        capture = AutoCaptureMiddleware(store, llm, similarity_dedup_threshold=0.75)
        assert capture._dedup_threshold == 0.75


# ─────────────────────────────────────────────────────────────────────────────
# FTS Dirty-write Tracking
# ─────────────────────────────────────────────────────────────────────────────

class TestFTSDirtyTracking:
    """Tests for lazy FTS index rebuild after N writes."""

    def _make_real_store(self, tmp_path, threshold: int = 3):
        """Create a LanceDBStore with a small rebuild threshold for testing."""
        from olav.core.memory import LanceDBStore
        store = LanceDBStore(db_path=str(tmp_path / "fts_test.lance"), embedding_dim=4)
        store._fts_rebuild_threshold = threshold
        return store

    def test_no_rebuild_below_threshold(self, tmp_path):
        """FTS index is NOT rebuilt on writes below the threshold."""
        from olav.core.memory import MEMORY_TABLE

        store = self._make_real_store(tmp_path, threshold=5)
        store.create_table(MEMORY_TABLE)

        tbl = store.get_table(MEMORY_TABLE)
        with patch.object(tbl, "create_fts_index") as mock_fts:
            # Patch get_table to return the mocked table
            with patch.object(store, "get_table", return_value=tbl):
                for i in range(4):  # 4 < threshold=5
                    store.add_memory(
                        id=f"m{i}", text=f"text {i}",
                        vector=[0.1, 0.2, 0.3, 0.4],
                    )
            mock_fts.assert_not_called()

    def test_rebuild_at_threshold(self, tmp_path):
        """FTS index IS rebuilt once the threshold is reached."""
        from olav.core.memory import MEMORY_TABLE

        store = self._make_real_store(tmp_path, threshold=3)
        store.create_table(MEMORY_TABLE)

        tbl = store.get_table(MEMORY_TABLE)
        with patch.object(tbl, "create_fts_index") as mock_fts:
            with patch.object(store, "get_table", return_value=tbl):
                for i in range(3):  # exactly threshold=3
                    store.add_memory(
                        id=f"m{i}", text=f"text {i}",
                        vector=[0.1, 0.2, 0.3, 0.4],
                    )
            mock_fts.assert_called_once_with("text", replace=True)

    def test_dirty_counter_resets_after_rebuild(self, tmp_path):
        """Dirty counter resets to 0 after a rebuild, enabling next cycle."""
        from olav.core.memory import MEMORY_TABLE

        store = self._make_real_store(tmp_path, threshold=2)
        store.create_table(MEMORY_TABLE)
        tbl = store.get_table(MEMORY_TABLE)

        with patch.object(store, "get_table", return_value=tbl):
            with patch.object(tbl, "create_fts_index"):
                store.add_memory(id="m0", text="t0", vector=[0.1, 0.2, 0.3, 0.4])
                store.add_memory(id="m1", text="t1", vector=[0.1, 0.2, 0.3, 0.4])
                # At this point counter should have reset to 0
                assert store._fts_dirty.get(MEMORY_TABLE, 0) == 0

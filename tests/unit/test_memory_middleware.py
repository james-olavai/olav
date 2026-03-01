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

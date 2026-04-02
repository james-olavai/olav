"""TDD tests for SemanticCache semantic_cache_hit audit event (P2-2).

Verifies that SemanticCache.get() emits a ``semantic_cache_hit`` event to
AuditEventRecorder when a cache hit occurs and recorder+run_id are supplied.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_recorder(db_path: Path):
    from olav.core.audit_recorder import AuditEventRecorder
    return AuditEventRecorder(db_path=db_path)


def _make_cache(store=None):
    from olav.core.memory import SemanticCache
    if store is None:
        store = MagicMock()
    return SemanticCache(store=store, threshold=0.05)


# ---------------------------------------------------------------------------
# Cache HIT path
# ---------------------------------------------------------------------------


def test_cache_hit_emits_semantic_cache_hit(tmp_path: Path):
    """When get() returns cached results, semantic_cache_hit must be recorded."""
    recorder = _make_recorder(tmp_path / "audit.duckdb")
    run_id = str(uuid.uuid4())
    cache = _make_cache()

    cached_results = [{"id": "mem-1", "content": "interface GigE0 is up"}]

    with patch.object(cache, "_ensure_table") as mock_table_fn:
        mock_table = MagicMock()
        mock_table.count_rows.return_value = 1
        mock_table.search.return_value.limit.return_value.to_list.return_value = [
            {"_distance": 0.01, "result_json": json.dumps(cached_results), "created_at": None}
        ]
        mock_table_fn.return_value = mock_table

        result = cache.get([0.1, 0.2, 0.3], recorder=recorder, run_id=run_id)

    assert result == cached_results, f"Wrong result: {result}"

    recorder.close()
    with duckdb.connect(str(recorder._db_path)) as _c:
        rows = _c.execute("SELECT event_type, payload FROM audit_events").fetchall()
    assert rows, "No event written on cache hit"
    event_type, payload_str = rows[0]
    assert event_type == "semantic_cache_hit", f"Got {event_type}"
    payload = json.loads(payload_str)
    assert "distance" in payload
    assert abs(payload["distance"] - 0.01) < 1e-6


# ---------------------------------------------------------------------------
# Cache MISS path — no event
# ---------------------------------------------------------------------------


def test_cache_miss_no_event(tmp_path: Path):
    """A cache miss (distance > threshold) must not write any event."""
    recorder = _make_recorder(tmp_path / "audit.duckdb")
    run_id = str(uuid.uuid4())
    cache = _make_cache()  # threshold=0.05

    with patch.object(cache, "_ensure_table") as mock_table_fn:
        mock_table = MagicMock()
        mock_table.count_rows.return_value = 1
        mock_table.search.return_value.limit.return_value.to_list.return_value = [
            {"_distance": 0.30, "result_json": "[]", "created_at": None}
        ]
        mock_table_fn.return_value = mock_table

        result = cache.get([0.1, 0.2, 0.3], recorder=recorder, run_id=run_id)

    assert result is None
    recorder.close()
    with duckdb.connect(str(recorder._db_path)) as _c:
        count = _c.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    assert count == 0, "Miss should not produce an audit event"


def test_empty_table_no_event(tmp_path: Path):
    """Empty cache table (count=0) early-return must not write event."""
    recorder = _make_recorder(tmp_path / "audit.duckdb")
    run_id = str(uuid.uuid4())
    cache = _make_cache()

    with patch.object(cache, "_ensure_table") as mock_table_fn:
        mock_table = MagicMock()
        mock_table.count_rows.return_value = 0
        mock_table_fn.return_value = mock_table

        result = cache.get([0.1, 0.2, 0.3], recorder=recorder, run_id=run_id)

    assert result is None
    recorder.close()
    with duckdb.connect(str(recorder._db_path)) as _c:
        count = _c.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_cache_hit_no_recorder_no_crash():
    """Calling get() without recorder/run_id (existing callers) must work fine."""
    cache = _make_cache()
    cached_results = [{"id": "mem-1"}]

    with patch.object(cache, "_ensure_table") as mock_table_fn:
        mock_table = MagicMock()
        mock_table.count_rows.return_value = 1
        mock_table.search.return_value.limit.return_value.to_list.return_value = [
            {"_distance": 0.01, "result_json": json.dumps(cached_results), "created_at": None}
        ]
        mock_table_fn.return_value = mock_table

        result = cache.get([0.1, 0.2, 0.3])  # no recorder, no run_id

    assert result == cached_results


def test_cache_hit_recorder_no_run_id_no_event(tmp_path: Path):
    """recorder without run_id → hit still returned but no event written."""
    recorder = _make_recorder(tmp_path / "audit.duckdb")
    cache = _make_cache()
    cached_results = [{"id": "mem-1"}]

    with patch.object(cache, "_ensure_table") as mock_table_fn:
        mock_table = MagicMock()
        mock_table.count_rows.return_value = 1
        mock_table.search.return_value.limit.return_value.to_list.return_value = [
            {"_distance": 0.01, "result_json": json.dumps(cached_results), "created_at": None}
        ]
        mock_table_fn.return_value = mock_table

        result = cache.get([0.1, 0.2, 0.3], recorder=recorder)  # no run_id

    assert result == cached_results
    recorder.close()
    with duckdb.connect(str(recorder._db_path)) as _c:
        count = _c.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    assert count == 0, "No run_id → no event expected"

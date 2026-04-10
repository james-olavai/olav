"""Phase 3 TDD — unified search across agent + document origins.

C-KB-22: hybrid_search() returns results from both agent and document origins
         in the same query (unified memory table)
"""

import json
import pytest
import pyarrow as pa
from datetime import datetime

DIM = 32


def _make_store(tmp_path):
    from olav.core.memory import LanceDBStore
    return LanceDBStore(db_path=str(tmp_path / "search.db"), embedding_dim=DIM)


def _add(store, id_, text, origin, vector=None):
    from olav.core.memory import MEMORY_TABLE
    if not store.table_exists(MEMORY_TABLE):
        store.create_table()

    v = vector if vector is not None else [0.0] * DIM
    tbl = store.get_table()
    ts = datetime.now()
    record = pa.table(
        [pa.array([id_]), pa.array([text]), pa.array([v]),
         pa.array(["fact"]), pa.array(["global"]), pa.array(["{}"]),
         pa.array([ts]), pa.array([ts]),
         pa.array([1]), pa.array([1.0]),
         pa.array([origin]), pa.array([0.8], type=pa.float32()), pa.array(["[]"])],
        schema=store._get_schema(),
    )
    tbl.add(record)


# ─── C-KB-22: search returns agent + document entries ────────────────────────

def test_unified_search_returns_agent_memories(tmp_path):
    """C-KB-22: search_by_vector returns agent-origin memories."""
    store = _make_store(tmp_path)
    v = [1.0] + [0.0] * (DIM - 1)
    _add(store, "cap-001", "Agent captured: BGP session up.", "agent", vector=v)

    results = store.search_by_vector(query_vector=v, limit=5)
    ids = [r["id"] for r in results]
    assert "cap-001" in ids, f"Agent memory not found in search results: {ids}"


def test_unified_search_returns_document_memories(tmp_path):
    """C-KB-22: search_by_vector returns document-origin memories."""
    store = _make_store(tmp_path)
    v = [1.0] + [0.0] * (DIM - 1)
    _add(store, "doc-001", "RFC 7752 BGP-LS specification.", "document", vector=v)

    results = store.search_by_vector(query_vector=v, limit=5)
    ids = [r["id"] for r in results]
    assert "doc-001" in ids, f"Document memory not found in search results: {ids}"


def test_unified_search_returns_both_origins_together(tmp_path):
    """C-KB-22: a single search query returns both agent and document entries."""
    store = _make_store(tmp_path)
    # Use identical vectors so both should be near top
    v = [1.0] + [0.0] * (DIM - 1)
    _add(store, "cap-mixed", "Agent fact about BGP MTU.", "agent", vector=v)
    _add(store, "doc-mixed", "Document: BGP MTU troubleshooting.", "document", vector=v)

    results = store.search_by_vector(query_vector=v, limit=10)
    origins = {r["id"]: None for r in results}

    # Both should appear
    assert "cap-mixed" in {r["id"] for r in results}, (
        "agent-origin memory missing from unified search"
    )
    assert "doc-mixed" in {r["id"] for r in results}, (
        "document-origin memory missing from unified search"
    )


def test_unified_search_result_includes_origin_field(tmp_path):
    """C-KB-22: search results must include the 'origin' field."""
    store = _make_store(tmp_path)
    v = [1.0] + [0.0] * (DIM - 1)
    _add(store, "origin-check", "Some fact.", "agent", vector=v)

    results = store.search_by_vector(query_vector=v, limit=5)
    assert results, "Expected at least 1 result"
    for r in results:
        assert "origin" in r, f"Result missing 'origin' field: {r}"

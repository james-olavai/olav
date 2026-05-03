"""Pin LLM-only-mode read path: AutoRecallMiddleware._gather_candidates
must skip vector search and use search_by_text when query_vector is None.

The motivating contract: a deployment with ``embedding.mode = "none"``
or a transient embedder outage should still surface memories via
BM25/FTS — no crash, no silent zero-result.

Companion to ``test_commit_to_memory.py::*_writes_zero_vec_when_*``
which pins the write-side guarantee.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _build_mw(store):
    """Construct AutoRecallMiddleware bound to a mock store."""
    from olav.core.memory.middleware import AutoRecallMiddleware
    mw = AutoRecallMiddleware(store=store)
    return mw


def test_gather_candidates_with_none_vector_uses_search_by_text(monkeypatch):
    """query_vector=None → search_by_vector NEVER called; search_by_text IS."""
    store = MagicMock()
    store.search_by_vector = MagicMock(side_effect=AssertionError(
        "search_by_vector must NOT be called when query_vector is None"
    ))
    store.search_by_text = MagicMock(return_value=[
        {"id": "m1", "text": "hit 1", "category": "fact", "scope": "global"},
        {"id": "m2", "text": "hit 2", "category": "fact", "scope": "global"},
    ])

    mw = _build_mw(store)
    out = mw._gather_candidates(
        query_text="how does R1 BGP work",
        query_vector=None,  # ← the LLM-only mode condition
        scope="global",
        top_k=5,
    )

    # search_by_vector should not be touched
    store.search_by_vector.assert_not_called()
    # search_by_text should be the only retrieval
    assert store.search_by_text.call_count == 1
    call_kwargs = store.search_by_text.call_args.kwargs
    assert call_kwargs["query"] == "how does R1 BGP work"
    assert call_kwargs["scope"] == "global"
    # Returned candidates contain what search_by_text gave us
    assert {m["id"] for m in out} == {"m1", "m2"}


def test_gather_candidates_with_vector_uses_hybrid(monkeypatch):
    """Sanity: with a real vector, vector-path is used (existing behaviour)."""
    store = MagicMock()
    store.search_by_vector = MagicMock(return_value=[])  # empty per-category
    store.search_by_text = MagicMock(side_effect=AssertionError(
        "search_by_text fallback should NOT fire when vector is present"
    ))

    # Patch hybrid_search to a stub that returns one row, so the
    # long-tail block exits cleanly.
    import olav.core.memory.middleware as mw_mod
    monkeypatch.setattr(mw_mod, "hybrid_search", lambda **kw: [
        {"id": "h1", "text": "hybrid hit", "category": "fact", "scope": "global"},
    ])

    mw = _build_mw(store)
    out = mw._gather_candidates(
        query_text="some query",
        query_vector=[0.1, 0.2, 0.3],
        scope="global",
        top_k=5,
    )

    store.search_by_text.assert_not_called()
    assert {m["id"] for m in out} == {"h1"}


def test_search_by_text_failure_returns_empty_not_crash(monkeypatch):
    """If search_by_text itself blows up, _gather_candidates returns []
    (degraded gracefully — agent still answers, just without memory)."""
    store = MagicMock()
    store.search_by_vector = MagicMock(side_effect=AssertionError("not called"))
    store.search_by_text = MagicMock(side_effect=RuntimeError("FTS index missing"))

    mw = _build_mw(store)
    out = mw._gather_candidates(
        query_text="anything",
        query_vector=None,
        scope="global",
        top_k=5,
    )

    assert out == []

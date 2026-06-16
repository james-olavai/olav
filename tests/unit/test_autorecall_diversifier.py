"""R83.4 follow-up: AutoRecall diversifier + curated-category gather.

Memory poisoning regression: when a question is asked many times, the
``query_pattern`` capture middleware accumulates near-identical entries
that all rank near the top of hybrid (vector+BM25) search. This crowds
out ``schema_knowledge`` and ``value_distribution`` entries written by
``memory_primer``, leaving cross-platform questions stuck on whichever
view the very first successful answer happened to use.

The fix has two prongs:
1. ``_gather_candidates`` issues an explicit per-category vector query so
   curated entries always have a fair shot.
2. ``_diversify_by_category`` caps ``query_pattern`` to 1 in the final
   top-K and reserves quota slots for ``schema_knowledge`` and
   ``value_distribution``.
"""

from __future__ import annotations

import pytest


def _mk(mid: str, cat: str) -> dict:
    return {"id": mid, "category": cat, "text": mid}


def test_diversifier_caps_query_pattern_at_two():
    """CC-1c (dev_docs/58): cap raised 1 → 2 to give captured SQL a
    foothold while still protecting against accumulating-near-duplicates
    poisoning the recall.  Original test pinned cap=1 (R83.4)."""
    from olav.core.memory.middleware import AutoRecallMiddleware

    mw = AutoRecallMiddleware(store=None)
    raw = [
        _mk("qp_1", "query_pattern"),
        _mk("qp_2", "query_pattern"),
        _mk("qp_3", "query_pattern"),
        _mk("qp_4", "query_pattern"),
        _mk("schema_a", "schema_knowledge"),
        _mk("schema_b", "schema_knowledge"),
        _mk("values_a", "value_distribution"),
        _mk("values_b", "value_distribution"),
    ]
    out = mw._diversify_by_category(raw, limit=8)
    cats = [m["category"] for m in out]
    assert cats.count("query_pattern") == 2


def test_diversifier_preserves_global_rank_order():
    from olav.core.memory.middleware import AutoRecallMiddleware

    mw = AutoRecallMiddleware(store=None)
    raw = [
        _mk("schema_a", "schema_knowledge"),
        _mk("qp_1", "query_pattern"),
        _mk("values_a", "value_distribution"),
        _mk("schema_b", "schema_knowledge"),
    ]
    out = mw._diversify_by_category(raw, limit=4)
    # All 4 admitted (no caps hit), order preserved
    assert [m["id"] for m in out] == ["schema_a", "qp_1", "values_a", "schema_b"]


def test_gather_candidates_fetches_curated_categories(monkeypatch):
    """Each curated category must get its own vector query so that one
    category's RRF ranking can't starve another."""
    from olav.core.memory.middleware import AutoRecallMiddleware

    calls = []

    class _Store:
        def search_by_vector(self, query_vector, limit, category=None, scope=None):
            calls.append(("vec", category, limit))
            # Return distinct items per category so dedup behaves
            return [_mk(f"{category}_{i}", category) for i in range(limit)]

    # No-op for the long-tail hybrid pass.
    monkeypatch.setattr(
        "olav.core.memory.middleware.hybrid_search",
        lambda **kw: [],
    )

    mw = AutoRecallMiddleware(store=_Store())
    out = mw._gather_candidates("q", [0.0, 0.1, 0.2], scope=None, top_k=8)

    queried = {c for _, c, _ in calls}
    # schema_knowledge + value_distribution removed in ISSUE-SCHEMA-PUSH-VS-PULL
    # (dev_docs/00, 2026-04-30); curated categories are now query_pattern,
    # usage_guide, and expert_knowledge
    assert "query_pattern" in queried
    assert "usage_guide" in queried
    assert "expert_knowledge" in queried

    # The curated entries should be in the candidate list.
    ids = [m["id"] for m in out]
    assert any("query_pattern_" in i for i in ids)
    assert any("usage_guide_" in i for i in ids)


def test_gather_then_diversify_surfaces_multiple_curated_categories(monkeypatch):
    """End-to-end: curated gather + diversifier must include entries from
    multiple curated categories (usage_guide + query_pattern) when both
    are available, even when BM25 would otherwise starve one category.
    NOTE: schema_knowledge / value_distribution were removed in
    ISSUE-SCHEMA-PUSH-VS-PULL (dev_docs/00, 2026-04-30)."""
    from olav.core.memory.middleware import AutoRecallMiddleware

    guide_a = _mk("guide_interface_troubleshooting", "usage_guide")
    guide_b = _mk("guide_bgp_peer_down", "usage_guide")
    qp_a = _mk("qp_interfaces_down_query", "query_pattern")
    expert_a = _mk("expert_junos_interface_naming", "expert_knowledge")

    class _Store:
        def search_by_vector(self, query_vector, limit, category=None, scope=None):
            if category == "usage_guide":
                return [guide_a, guide_b][:limit]
            if category == "query_pattern":
                return [qp_a][:limit]
            if category == "expert_knowledge":
                return [expert_a][:limit]
            return []

    monkeypatch.setattr(
        "olav.core.memory.middleware.hybrid_search",
        lambda **kw: [],
    )

    mw = AutoRecallMiddleware(store=_Store(), top_k=6)
    raw = mw._gather_candidates("which interfaces are down", [0.1] * 5, scope=None, top_k=6)
    out = mw._diversify_by_category(raw, limit=6)
    ids = {m["id"] for m in out}
    assert "guide_interface_troubleshooting" in ids, (
        "usage_guide entry must survive into top-K"
    )
    assert "qp_interfaces_down_query" in ids, (
        "query_pattern entry must survive into top-K"
    )

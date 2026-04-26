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
    """CC-1c (dev_docs/62): cap raised 1 → 2 to give captured SQL a
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
    assert "schema_knowledge" in queried
    assert "value_distribution" in queried
    assert "query_pattern" in queried

    # The curated entries should be in the candidate list.
    ids = [m["id"] for m in out]
    assert any("schema_knowledge_" in i for i in ids)
    assert any("value_distribution_" in i for i in ids)


def test_gather_then_diversify_surfaces_cross_platform_schema(monkeypatch):
    """End-to-end: curated gather + diversifier must include schemas from
    multiple platforms even when one platform's view dominates BM25."""
    from olav.core.memory.middleware import AutoRecallMiddleware

    cisco_schema = _mk("schema_v_show_ip_interface_brief_auto", "schema_knowledge")
    junos_schema = _mk("schema_v_show_interfaces_terse_auto", "schema_knowledge")
    other_schema = _mk("schema_v_show_interfaces_auto", "schema_knowledge")
    cisco_values = _mk("values_brief_status", "value_distribution")
    junos_values = _mk("values_terse_link_state", "value_distribution")

    class _Store:
        def search_by_vector(self, query_vector, limit, category=None, scope=None):
            if category == "schema_knowledge":
                return [cisco_schema, junos_schema, other_schema][:limit]
            if category == "value_distribution":
                return [cisco_values, junos_values][:limit]
            if category == "query_pattern":
                return []
            return []

    # Hybrid would return cisco-leaning poisoned results — exclude here.
    monkeypatch.setattr(
        "olav.core.memory.middleware.hybrid_search",
        lambda **kw: [],
    )

    mw = AutoRecallMiddleware(store=_Store(), top_k=6)
    raw = mw._gather_candidates("which interfaces are down", [0.1] * 5, scope=None, top_k=6)
    out = mw._diversify_by_category(raw, limit=6)
    ids = {m["id"] for m in out}
    assert "schema_v_show_interfaces_terse_auto" in ids, (
        "Junos terse schema must survive into top-K so cross-platform "
        "questions reach both Cisco and Junos data."
    )
    assert "schema_v_show_ip_interface_brief_auto" in ids

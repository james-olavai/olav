"""CC-1c: query_pattern was being starved out of the diversifier — fix.

Bug discovered while diagnosing Q3 +167% drift (dev_docs/62 § "CC-1b
structural diagnosis"):

* ``_CATEGORY_CAPS["query_pattern"] = 1`` — hard cap of 1
* ``_CATEGORY_QUOTAS`` reserves 5 schema + 5 value + 3 guide = 13
  slots, leaving none for query_pattern

Combined effect: even with 5 perfectly-relevant Q3 SQL patterns
captured by ``query_pattern_capture``, the diversifier returns 0
query_pattern hits because Pass 2 fills the entire ``recall_top_k=13``
budget before query_pattern gets a slot.

Fix: lift the cap to 2 + add 2-slot quota; rebalance schema/value
down by 1 each so the total stays at 13.
"""

from __future__ import annotations


def _mk(mid: str, cat: str) -> dict:
    return {"id": mid, "category": cat, "text": mid}


# ── new contract ────────────────────────────────────────────────────


def test_diversifier_returns_query_pattern_when_budget_has_room():
    """When the input has 5 query_pattern + plenty of others, top-13
    must include 2 query_patterns (the new quota)."""
    from olav.core.memory.middleware import AutoRecallMiddleware

    mw = AutoRecallMiddleware(store=None)
    raw = (
        [_mk(f"qp_{i}", "query_pattern") for i in range(5)]
        + [_mk(f"schema_{i}", "schema_knowledge") for i in range(6)]
        + [_mk(f"values_{i}", "value_distribution") for i in range(6)]
        + [_mk(f"guide_{i}", "usage_guide") for i in range(4)]
    )
    out = mw._diversify_by_category(raw, limit=13)
    cats = [m["category"] for m in out]
    assert cats.count("query_pattern") == 2, (
        f"Expected 2 query_pattern slots in top-13; got {cats}"
    )


def test_diversifier_total_slots_sum():
    """Quota dict must be consistent — all values positive, total > 0."""
    from olav.core.memory.middleware import AutoRecallMiddleware

    total = sum(AutoRecallMiddleware._CATEGORY_QUOTAS.values())
    assert total > 0, f"Total quota must be positive; got {total}"
    # All individual quotas must be positive too
    for cat, n in AutoRecallMiddleware._CATEGORY_QUOTAS.items():
        assert n > 0, f"quota for {cat!r} must be positive; got {n}"


def test_diversifier_quota_distribution():
    """Post-ISSUE-SCHEMA-PUSH-VS-PULL quota distribution (2026-04-30):
    schema_knowledge + value_distribution removed; curated categories are
    now query_pattern, usage_guide, format_guide, expert_knowledge.
    Lineage:
      pre-CC-1c                5+5+0+3        = 13 (schema+value+guide)
      CC-1c                    4+4+2+3        = 13 (added query_pattern)
      R85 δ2                   3+4+2+3+1      = 13 (added format_guide)
      R87 Phase 1              2+4+2+3+1+1    = 13 (added expert_knowledge)
      ISSUE-SCHEMA-PUSH-VS-PULL 0+0+2+3+1+3   = 9  (removed schema+value)
      TRACE-LEARN-WIRING (2026-06-12) +reflection:1 = 10 (trace_learner
                               failure constraints, scope=global)
    """
    from olav.core.memory.middleware import AutoRecallMiddleware

    q = AutoRecallMiddleware._CATEGORY_QUOTAS
    assert q["query_pattern"] == 2
    assert q["usage_guide"] == 3
    assert q["format_guide"] == 1
    assert q["expert_knowledge"] == 3
    assert q["reflection"] == 1
    assert "schema_knowledge" not in q, "schema_knowledge was intentionally removed"
    assert "value_distribution" not in q, "value_distribution was intentionally removed"


def test_diversifier_cap_allows_two_query_patterns():
    """Hard cap is 2 (was 1) — protects against 5+ near-duplicate
    captures while leaving room for the quota to actually fire."""
    from olav.core.memory.middleware import AutoRecallMiddleware

    cap = AutoRecallMiddleware._CATEGORY_CAPS.get("query_pattern")
    assert cap == 2, f"Expected cap=2 for query_pattern; got {cap}"


# ── regression-guard for the original poisoning fix ────────────────


def test_diversifier_still_caps_runaway_query_pattern_growth():
    """If 100 near-duplicate query_patterns flood the input, the cap
    still protects: only 2 reach the diversifier output (not 100)."""
    from olav.core.memory.middleware import AutoRecallMiddleware

    mw = AutoRecallMiddleware(store=None)
    raw = (
        [_mk(f"qp_{i}", "query_pattern") for i in range(100)]
        + [_mk(f"schema_{i}", "schema_knowledge") for i in range(6)]
        + [_mk(f"values_{i}", "value_distribution") for i in range(6)]
    )
    out = mw._diversify_by_category(raw, limit=13)
    cats = [m["category"] for m in out]
    assert cats.count("query_pattern") <= 2, (
        f"query_pattern flood must be capped at 2; got {cats}"
    )

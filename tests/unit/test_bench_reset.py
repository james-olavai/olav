"""Bench-state reset helper — TDD red bar.

Pin the contract for ``olav.core.memory.bench_reset.reset_volatile_categories``
which the smallmodel bench harness will call once before each run to
make consecutive bench runs comparable.

Why: between bench runs the demo6 workspace accumulates
``query_pattern`` rows from prior agent runs.  By the time a second
bench fires, the diversifier's top-13 is half learned-SQL templates
that happen to influence the small model's exploration paths.
Q2/Q3 inflated +113%/+167% in the platform_kb refactor bench despite
byte-for-byte equivalent code — that's the contamination this helper
removes.

See dev_docs/58 § "CC-1: Bench harness reset between runs".
"""

from __future__ import annotations

from unittest.mock import patch


DIM = 32


def _make_store(tmp_path):
    from olav.core.memory import LanceDBStore
    store = LanceDBStore(db_path=str(tmp_path / "bench.db"), embedding_dim=DIM)
    store.create_table()
    return store


def _embed_stub(text: str) -> list[float]:
    return [float(len(text) % 100) / 100.0] * DIM


def _seed_memory(store, *, category: str, mem_id: str, text: str = "x"):
    """Add one memory row directly (no embedding network calls)."""
    store.add_memory(
        id=mem_id,
        text=text,
        vector=_embed_stub(text),
        category=category,
        scope="global",
        metadata={},
        origin="test",
        confidence=1.0,
        tags="[]",
    )


def _count(store, category: str) -> int:
    memories = store.get_memories(limit=1000)
    return sum(1 for m in memories if m["category"] == category)


# ── default categories ──────────────────────────────────────────────


def test_reset_clears_query_pattern(tmp_path):
    """``query_pattern`` rows are dropped by default."""
    store = _make_store(tmp_path)
    _seed_memory(store, category="query_pattern", mem_id="qp1")
    _seed_memory(store, category="query_pattern", mem_id="qp2")

    from olav.core.memory.bench_reset import reset_volatile_categories
    out = reset_volatile_categories(store)

    assert _count(store, "query_pattern") == 0
    assert out["cleared"]["query_pattern"] == 2


def test_reset_preserves_usage_guide(tmp_path):
    """``usage_guide`` rows are NOT dropped — they're idempotent re-prime targets."""
    store = _make_store(tmp_path)
    _seed_memory(store, category="usage_guide", mem_id="guide_ops_topology")
    _seed_memory(store, category="query_pattern", mem_id="qp1")

    from olav.core.memory.bench_reset import reset_volatile_categories
    reset_volatile_categories(store)

    assert _count(store, "usage_guide") == 1
    assert _count(store, "query_pattern") == 0


def test_reset_preserves_schema_knowledge(tmp_path):
    """``schema_knowledge`` rows are NOT dropped — they're netops_init artefacts."""
    store = _make_store(tmp_path)
    _seed_memory(store, category="schema_knowledge", mem_id="schema_v_x")
    _seed_memory(store, category="query_pattern", mem_id="qp1")

    from olav.core.memory.bench_reset import reset_volatile_categories
    reset_volatile_categories(store)

    assert _count(store, "schema_knowledge") == 1


def test_reset_preserves_value_distribution(tmp_path):
    """``value_distribution`` rows are NOT dropped."""
    store = _make_store(tmp_path)
    _seed_memory(store, category="value_distribution", mem_id="values_v_x_status")
    _seed_memory(store, category="query_pattern", mem_id="qp1")

    from olav.core.memory.bench_reset import reset_volatile_categories
    reset_volatile_categories(store)

    assert _count(store, "value_distribution") == 1


def test_reset_returns_count_dict(tmp_path):
    """Return shape: {'cleared': {cat: N}, 'preserved': {cat: M}}."""
    store = _make_store(tmp_path)
    _seed_memory(store, category="query_pattern", mem_id="qp1")
    _seed_memory(store, category="usage_guide", mem_id="guide_x")

    from olav.core.memory.bench_reset import reset_volatile_categories
    out = reset_volatile_categories(store)

    assert isinstance(out, dict)
    assert "cleared" in out
    assert "preserved" in out
    assert out["cleared"]["query_pattern"] == 1
    assert out["preserved"]["usage_guide"] == 1


# ── opt-in extra categories ─────────────────────────────────────────


def test_reset_can_opt_in_to_clearing_fact_and_decision(tmp_path):
    """When categories=('query_pattern','fact','decision'), all three drop."""
    store = _make_store(tmp_path)
    _seed_memory(store, category="query_pattern", mem_id="qp1")
    _seed_memory(store, category="fact", mem_id="f1")
    _seed_memory(store, category="decision", mem_id="d1")
    _seed_memory(store, category="usage_guide", mem_id="guide_x")

    from olav.core.memory.bench_reset import reset_volatile_categories
    reset_volatile_categories(
        store,
        categories=("query_pattern", "fact", "decision"),
    )

    assert _count(store, "query_pattern") == 0
    assert _count(store, "fact") == 0
    assert _count(store, "decision") == 0
    assert _count(store, "usage_guide") == 1


def test_reset_idempotent_on_empty_store(tmp_path):
    """Reset on a store with no matching rows → cleared counts all zero."""
    store = _make_store(tmp_path)
    _seed_memory(store, category="usage_guide", mem_id="guide_x")

    from olav.core.memory.bench_reset import reset_volatile_categories
    out = reset_volatile_categories(store)

    assert out["cleared"]["query_pattern"] == 0
    assert out["preserved"]["usage_guide"] == 1

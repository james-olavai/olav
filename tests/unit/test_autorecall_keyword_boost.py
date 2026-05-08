"""Tests for AutoRecallMiddleware._boost_keyword_exact_match (Patch C2).

Pure unit test — exercises the boost helper directly without the full
recall pipeline so the assertions are unambiguous.
"""
from __future__ import annotations

from unittest.mock import MagicMock


def _make_mw():
    """Construct an AutoRecallMiddleware with a MagicMock store.

    We're testing the pure list-shuffling helpers; no actual store
    operations need to work.
    """
    from olav.core.memory.middleware import AutoRecallMiddleware
    return AutoRecallMiddleware(MagicMock())


# ── _extract_query_keywords ─────────────────────────────────────────


def test_extract_keywords_picks_snake_case_multi_word():
    mw = _make_mw()
    kws = mw._extract_query_keywords(
        "Please call emit_tcf for change_id=foo and validate_tcf_in_lab next"
    )
    assert "emit_tcf" in kws
    assert "validate_tcf_in_lab" in kws
    assert "change_id" in kws


def test_extract_keywords_skips_single_word():
    mw = _make_mw()
    kws = mw._extract_query_keywords("List all hostnames in the inventory")
    # No multi-word snake_case identifier present
    assert kws == set()


def test_extract_keywords_handles_empty_query():
    mw = _make_mw()
    assert mw._extract_query_keywords("") == set()
    assert mw._extract_query_keywords(None) == set()


def test_extract_keywords_strips_sql_stoplist():
    mw = _make_mw()
    kws = mw._extract_query_keywords(
        "SELECT * FROM netops.devices order_by hostname group_by site"
    )
    # order_by / group_by are stoplist; netops.devices not snake (has dot)
    assert "order_by" not in kws
    assert "group_by" not in kws


# ── _boost_keyword_exact_match ──────────────────────────────────────


def test_boost_promotes_text_match():
    """Memory whose ``text`` contains the query keyword wins."""
    mw = _make_mw()
    memories = [
        {"id": "a", "text": "BGP best path selection algorithm.", "tags": "[]"},
        {"id": "b", "text": "Use emit_tcf to write a CAB spec.", "tags": "[]"},
        {"id": "c", "text": "Diagram format choice + Mermaid examples.", "tags": "[]"},
    ]
    out = mw._boost_keyword_exact_match(memories, "Please call emit_tcf for X")
    # 'b' was at index 1, now at index 0
    assert out[0]["id"] == "b"
    # other order preserved
    assert out[1]["id"] == "a"
    assert out[2]["id"] == "c"


def test_boost_promotes_tags_match():
    """Memory whose ``tags`` contains the keyword also gets boosted."""
    mw = _make_mw()
    memories = [
        {"id": "a", "text": "Generic content.", "tags": "[]"},
        {"id": "b", "text": "Generic content.", "tags": '["emit_tcf", "cab"]'},
    ]
    out = mw._boost_keyword_exact_match(memories, "emit_tcf for ebgp")
    assert out[0]["id"] == "b"


def test_boost_handles_list_tags_field():
    """Tags can be a list (in-memory) or JSON string (from LanceDB)."""
    mw = _make_mw()
    memories = [
        {"id": "a", "text": "x", "tags": "[]"},
        {"id": "b", "text": "x", "tags": ["emit_tcf", "ops"]},
    ]
    out = mw._boost_keyword_exact_match(memories, "use emit_tcf please")
    assert out[0]["id"] == "b"


def test_boost_no_match_returns_unchanged():
    """No keyword in query → list unchanged."""
    mw = _make_mw()
    memories = [
        {"id": "a", "text": "x", "tags": "[]"},
        {"id": "b", "text": "y", "tags": "[]"},
    ]
    out = mw._boost_keyword_exact_match(memories, "Hi there")
    assert [m["id"] for m in out] == ["a", "b"]


def test_boost_empty_memories_returns_empty():
    mw = _make_mw()
    assert mw._boost_keyword_exact_match([], "emit_tcf foo") == []


def test_boost_preserves_relative_order_within_boosted_and_rest():
    """When multiple memories match, their relative order is preserved
    (so a same-keyword fight stays vector-cosine-ranked, just promoted
    over non-matches)."""
    mw = _make_mw()
    memories = [
        {"id": "a1", "text": "no match here", "tags": "[]"},
        {"id": "b1", "text": "uses emit_tcf in body", "tags": "[]"},
        {"id": "a2", "text": "also nothing", "tags": "[]"},
        {"id": "b2", "text": "another emit_tcf line", "tags": "[]"},
    ]
    out = mw._boost_keyword_exact_match(memories, "Run emit_tcf now")
    assert [m["id"] for m in out] == ["b1", "b2", "a1", "a2"]


def test_boost_realistic_cab_emit_scenario():
    """Reproduces the 2026-05-07 regression: change_plan_emit_tcf at
    rank #4, generic guides at top.  After boost, emit guide moves up."""
    mw = _make_mw()
    memories = [
        {"id": "guide_core_bgp_path", "text": "BGP path selection.", "tags": "[]"},
        {"id": "guide_core_diagrams", "text": "Mermaid format choice.", "tags": "[]"},
        {"id": "guide_core_schema_introspection", "text": "describe_table.", "tags": "[]"},
        {"id": "guide_ops_change_plan_emit_tcf",
         "text": "Change plan / TCF emission requests. Call emit_tcf @tool.",
         "tags": '["emit_tcf", "change_plan_emit_tcf"]'},
        {"id": "guide_ops_simulation_what_if", "text": "What-if simulation.", "tags": "[]"},
    ]
    query = (
        "emit_tcf for change_id=r1-r3-ebgp, intent_type=ebgp_direct, "
        "devices R1 (juniper_junos, AS 65001) and R3 (cisco_ios, AS 65000)"
    )
    out = mw._boost_keyword_exact_match(memories, query)
    # change_plan_emit_tcf was rank #4 — must now be at rank #1
    assert out[0]["id"] == "guide_ops_change_plan_emit_tcf"

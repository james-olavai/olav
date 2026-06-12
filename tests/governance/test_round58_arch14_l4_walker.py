"""Round 58 — ARCH-14 P3 deterministic clause walker.

Adds ``model.l4.walk(device, policy_name, matches)`` — the foundational
building block for policy evaluation. Lets callers supply their own
``matches`` function (dict-lookup for pure-SQL determinism, callable
for LLM-as-interpreter, ``None`` for "what if everything matched")
and returns a structured action + trace.

Pins:

* Deterministic clause ordering (by seq)
* Cisco AND-semantics on multi-match clauses
* ``implicit_deny`` when no clause matches
* ``missing=True`` when the policy doesn't exist on the device
* Dict-lookup matcher path — caller maps condition strings to bool
* Callable matcher path — allows LLM-style plug-in
* ``None`` matcher — every condition resolves True
* Unknown shape (e.g. list) → conservative False
* ``deny`` clauses don't return ``set`` actions
* ``model.l4.policy(...)`` continues raising — neighbor/direction
  resolution is a later round
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import duckdb
import pytest

from olav_netops.sim import load_network_model

HAS_NETWORKX = importlib.util.find_spec("networkx") is not None


_SAMPLE_CONFIG = """\
!
hostname R1
!
route-map POLICY permit 10
 match ip address prefix-list CUSTOMERS
 match community CUST_COMM
 set local-preference 200
 set community 65001:100
!
route-map POLICY deny 20
 match ip address prefix-list RESERVED
!
route-map POLICY permit 30
 set local-preference 50
!
route-map NEVER permit 10
 match as-path 50
!
"""


@pytest.fixture()
def walker_db(tmp_path: Path) -> Path:
    db = tmp_path / "walker.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        conn.execute(
            """
            CREATE TABLE netops.raw_output_store (
                device_name VARCHAR,
                command     VARCHAR,
                raw_output  TEXT,
                snapshot_id VARCHAR,
                created_at  TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO netops.raw_output_store VALUES "
            "('R1', 'show running-config', ?, 'snap_a', NOW())",
            [_SAMPLE_CONFIG],
        )
    return db


# ── Deterministic walker pins ───────────────────────────────────────────


def test_walk_permits_when_all_match_rules_hold(walker_db):
    m = load_network_model(db_path=walker_db)
    result = m.l4.walk("R1", "POLICY", matches={
        "ip address prefix-list CUSTOMERS": True,
        "community CUST_COMM": True,
    })
    if not HAS_NETWORKX:
        assert result["missing"] is True
        assert result["action"] == "implicit_deny"
        return
    assert result["action"] == "permit"
    assert set(result["sets"]) == {"local-preference 200", "community 65001:100"}


def test_walk_denies_when_second_clause_matches(walker_db):
    m = load_network_model(db_path=walker_db)
    # First clause fails (CUSTOMERS not matched), second clause (deny)
    # matches on RESERVED. Deny wins; no sets returned.
    result = m.l4.walk("R1", "POLICY", matches={
        "ip address prefix-list CUSTOMERS": False,
        "community CUST_COMM": False,
        "ip address prefix-list RESERVED": True,
    })
    if not HAS_NETWORKX:
        assert result["missing"] is True
        assert result["action"] == "implicit_deny"
        return
    assert result["action"] == "deny"
    assert result["sets"] == []


def test_walk_falls_through_to_third_clause(walker_db):
    """Cisco semantics: clauses evaluate in seq order; first match wins.
    When neither seq 10 nor seq 20 match, seq 30 (no match rules →
    unconditional) kicks in and permits."""
    m = load_network_model(db_path=walker_db)
    result = m.l4.walk("R1", "POLICY", matches={
        "ip address prefix-list CUSTOMERS": False,
        "community CUST_COMM": False,
        "ip address prefix-list RESERVED": False,
    })
    if not HAS_NETWORKX:
        assert result["missing"] is True
        assert result["action"] == "implicit_deny"
        return
    assert result["action"] == "permit"
    assert result["sets"] == ["local-preference 50"]


def test_walk_implicit_deny_when_only_clause_fails(walker_db):
    """NEVER only has one permit clause with a match; when that match
    fails the walker returns implicit_deny (Cisco default)."""
    m = load_network_model(db_path=walker_db)
    result = m.l4.walk("R1", "NEVER", matches={"as-path 50": False})
    if not HAS_NETWORKX:
        assert result["missing"] is True
        assert result["trace"] == []
        return
    assert result["action"] == "implicit_deny"
    assert result["sets"] == []


def test_walk_missing_policy_flag(walker_db):
    m = load_network_model(db_path=walker_db)
    result = m.l4.walk("R1", "DOES_NOT_EXIST", matches={})
    assert result["missing"] is True
    assert result["action"] == "implicit_deny"
    assert result["trace"] == []


def test_walk_missing_device_behaves_like_missing_policy(walker_db):
    m = load_network_model(db_path=walker_db)
    result = m.l4.walk("NO_SUCH_DEVICE", "POLICY", matches={})
    assert result["missing"] is True


# ── Trace structure pins ────────────────────────────────────────────────


def test_walk_trace_records_each_examined_clause(walker_db):
    m = load_network_model(db_path=walker_db)
    result = m.l4.walk("R1", "POLICY", matches={
        "ip address prefix-list CUSTOMERS": False,
        "community CUST_COMM": False,
        "ip address prefix-list RESERVED": False,
    })
    if not HAS_NETWORKX:
        assert result["trace"] == []
        assert result["missing"] is True
        return
    # seq 10 (skipped because match failed) + seq 20 (skipped) +
    # seq 30 (matched, permit) — trace should span all three.
    seqs = [e["seq"] for e in result["trace"]]
    assert seqs == [10, 20, 30]
    # First entry's match_results keys must surface the raw match
    # condition strings so operators can cross-reference to the config.
    assert "ip address prefix-list CUSTOMERS" in result["trace"][0]["match_results"]


def test_walk_trace_stops_at_first_match(walker_db):
    """Once a clause matches we stop — no later clause should appear in
    the trace (that's what the router does)."""
    m = load_network_model(db_path=walker_db)
    result = m.l4.walk("R1", "POLICY", matches={
        "ip address prefix-list CUSTOMERS": True,
        "community CUST_COMM": True,
    })
    if not HAS_NETWORKX:
        assert result["trace"] == []
        assert result["missing"] is True
        return
    seqs = [e["seq"] for e in result["trace"]]
    assert seqs == [10], (
        f"Walker should stop at seq 10 once matched; got {seqs}"
    )


def test_walk_trace_reason_strings(walker_db):
    m = load_network_model(db_path=walker_db)
    result = m.l4.walk("R1", "POLICY", matches={
        "ip address prefix-list CUSTOMERS": False,
        "community CUST_COMM": False,
        "ip address prefix-list RESERVED": True,
    })
    if not HAS_NETWORKX:
        assert result["trace"] == []
        assert result["missing"] is True
        return
    reasons = [e["reason"] for e in result["trace"]]
    # First clause fails on CUSTOMERS; second matches → deny.
    assert "match failed on" in reasons[0]
    assert "→ deny" in reasons[1]


# ── Matcher input-shape pins ────────────────────────────────────────────


def test_walk_with_callable_matcher(walker_db):
    m = load_network_model(db_path=walker_db)

    def _matcher(cond: str) -> bool:
        # Say yes only to the CUSTOMERS prefix-list — community fails.
        return "CUSTOMERS" in cond

    result = m.l4.walk("R1", "POLICY", matches=_matcher)
    if not HAS_NETWORKX:
        assert result["missing"] is True
        assert result["trace"] == []
        return
    # seq 10 has TWO match conditions; only CUSTOMERS holds → clause
    # skipped. seq 20's RESERVED returns False. Fall-through to seq 30
    # (unconditional permit).
    assert result["action"] == "permit"
    assert result["sets"] == ["local-preference 50"]


def test_walk_with_none_matcher_is_permissive(walker_db):
    """matches=None → every condition True → first permit wins."""
    m = load_network_model(db_path=walker_db)
    result = m.l4.walk("R1", "POLICY", matches=None)
    if not HAS_NETWORKX:
        assert result["missing"] is True
        assert result["trace"] == []
        return
    assert result["action"] == "permit"
    assert result["trace"][0]["seq"] == 10


def test_walk_with_unknown_matcher_shape_is_conservative(walker_db):
    """A caller passing a list or other unsupported shape must not be
    silently treated as match-everything — that would flip a deny into
    a permit. Walker returns False for every condition."""
    m = load_network_model(db_path=walker_db)
    result = m.l4.walk("R1", "POLICY", matches=["not a dict or callable"])
    if not HAS_NETWORKX:
        assert result["missing"] is True
        assert result["trace"] == []
        return
    # seq 10: both conditions False → skip.
    # seq 20: RESERVED False → skip.
    # seq 30: no match rules → unconditional match regardless of
    # matcher type.
    assert result["action"] == "permit"
    assert result["trace"][-1]["seq"] == 30


def test_walk_callable_raising_counts_as_false(walker_db):
    """Callable exceptions must be swallowed into False — a buggy
    matcher shouldn't blow up the walker."""
    m = load_network_model(db_path=walker_db)

    def _matcher(cond: str) -> bool:
        raise RuntimeError("matcher exploded")

    result = m.l4.walk("R1", "POLICY", matches=_matcher)
    if not HAS_NETWORKX:
        assert result["missing"] is True
        assert result["trace"] == []
        return
    # Conditions all resolve False; fall through to seq 30.
    assert result["action"] == "permit"
    assert result["trace"][0]["matched"] is False


# ── Deny-action pin + backward-compat pin ──────────────────────────────


def test_walk_deny_returns_no_sets(walker_db):
    m = load_network_model(db_path=walker_db)
    # Drive POLICY to deny via seq 20.
    result = m.l4.walk("R1", "POLICY", matches={
        "ip address prefix-list CUSTOMERS": False,
        "community CUST_COMM": False,
        "ip address prefix-list RESERVED": True,
    })
    if not HAS_NETWORKX:
        assert result["missing"] is True
        assert result["sets"] == []
        return
    assert result["action"] == "deny"
    assert result["sets"] == []


def test_l4_policy_integrates_walker_post_round_59():
    """Round 59 made ``.policy()`` real — it resolves the neighbor's
    route-map then delegates to walk(). This pin used to guard that
    ``.policy()`` raised; it now guards that the new surface is live
    and returns a well-formed structure even when no data is present."""
    m = load_network_model(db_path="/definitely/missing.duckdb")
    result = m.l4.policy(
        device="R1", neighbor="10.0.12.2", direction="out", matches={}
    )
    # With no config extracted, the binding is unbound → permit-all.
    assert isinstance(result, dict)
    assert result["unbound"] is True
    assert result["action"] == "permit"
    assert result["policy_name"] is None
    assert result["neighbor"] == "10.0.12.2"
    assert result["direction"] == "out"


def test_walk_private_helpers_have_expected_shape():
    """Pin helper presence so a refactor doesn't silently drop them."""
    from olav_netops.sim.network_model import (
        _evaluate_match_condition,
        _walk_reason,
    )
    assert callable(_evaluate_match_condition)
    assert callable(_walk_reason)
    # Fast sanity: dict lookup returning False for missing keys.
    assert _evaluate_match_condition({"a": True}, "b") is False
    assert _evaluate_match_condition({"a": True}, "a") is True
    # None → always True.
    assert _evaluate_match_condition(None, "anything") is True

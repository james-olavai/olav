"""Round 56 — ARCH-14 P2 L4 policy clause extraction (read-only).

Fills in ``model.l4`` with real Cisco IOS route-map parsing while
keeping ``model.l4.policy(...)`` as the P3 placeholder.

Contract this round pins:

* Raw ``netops.raw_output_store`` rows whose command looks like
  ``show running-config`` / ``show run`` get scanned.
* Each ``route-map NAME [permit|deny] SEQ`` stanza produces a clause
  record with ``policy_type``, ``policy_name``, ``action``, ``seq``,
  ``match: list[str]``, ``set: list[str]``, ``body: str``.
* ``model.l4.by_device`` / ``by_policy`` / ``policies`` / ``devices``
  / ``clauses`` / ``graph`` all return consistent data.
* ``model.l4.policy(...)`` raises ``NotImplementedError`` with a P3
  pointer so the evaluation contract stays stable.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import duckdb
import pytest

from olav_netops.sim import L4Layer, load_network_model

HAS_NETWORKX = importlib.util.find_spec("networkx") is not None


_SAMPLE_R1_CONFIG = """\
!
hostname R1
!
interface Gi0/1
 ip address 10.0.12.1 255.255.255.0
!
route-map EXPORT_CUSTOMERS permit 10
 match ip address prefix-list CUST_PREFIXES
 match community CUST_COMM
 set local-preference 200
 set community 65001:100
!
route-map EXPORT_CUSTOMERS deny 20
 match ip address prefix-list RESERVED
!
route-map IMPORT_INTERNET permit 10
 match as-path 50
 set local-preference 150
!
"""


_SAMPLE_R2_CONFIG = """\
!
hostname R2
!
route-map EXPORT_CUSTOMERS permit 10
 match ip address prefix-list CUST_PREFIXES
 set local-preference 210
!
"""


@pytest.fixture()
def l4_db(tmp_path: Path) -> Path:
    """DuckDB with running-config snapshots on R1 and R2."""
    db = tmp_path / "l4.duckdb"
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
            [_SAMPLE_R1_CONFIG],
        )
        conn.execute(
            "INSERT INTO netops.raw_output_store VALUES "
            "('R2', 'show run',             ?, 'snap_a', NOW())",
            [_SAMPLE_R2_CONFIG],
        )
        # Unrelated command must not influence the layer.
        conn.execute(
            "INSERT INTO netops.raw_output_store VALUES "
            "('R1', 'show version', 'IOS 15.7', 'snap_a', NOW())"
        )
    return db


# ── Lazy-proxy / cache pins ─────────────────────────────────────────────


def test_l4_is_l4layer_instance():
    m = load_network_model(db_path="/definitely/missing.duckdb")
    assert isinstance(m.l4, L4Layer)


def test_l4_caches_after_first_access(l4_db, monkeypatch):
    from olav_netops.sim import network_model as nm

    real_build = nm._build_l4_layer
    call_count = {"n": 0}

    def _spy(db, snap, scope):
        call_count["n"] += 1
        return real_build(db, snap, scope)

    monkeypatch.setattr(nm, "_build_l4_layer", _spy)
    m = load_network_model(db_path=l4_db)
    _ = m.l4
    _ = m.l4
    _ = m.l4
    assert call_count["n"] == 1


# ── Regex parser direct pins ────────────────────────────────────────────


def test_extract_route_maps_headers_and_bodies():
    from olav_netops.sim.network_model import _extract_route_maps_cisco_ios

    clauses = _extract_route_maps_cisco_ios(_SAMPLE_R1_CONFIG)
    # Three route-map stanzas in R1's config.
    assert len(clauses) == 3
    names = [c["policy_name"] for c in clauses]
    assert names == ["EXPORT_CUSTOMERS", "EXPORT_CUSTOMERS", "IMPORT_INTERNET"]
    seqs = [c["seq"] for c in clauses]
    assert seqs == [10, 20, 10]
    actions = [c["action"] for c in clauses]
    assert actions == ["permit", "deny", "permit"]


def test_extract_route_maps_captures_match_and_set():
    from olav_netops.sim.network_model import _extract_route_maps_cisco_ios

    clauses = _extract_route_maps_cisco_ios(_SAMPLE_R1_CONFIG)
    first = clauses[0]
    assert "ip address prefix-list CUST_PREFIXES" in first["match"]
    assert "community CUST_COMM" in first["match"]
    assert "local-preference 200" in first["set"]
    assert "community 65001:100" in first["set"]


def test_extract_route_maps_empty_input_graceful():
    from olav_netops.sim.network_model import _extract_route_maps_cisco_ios
    assert _extract_route_maps_cisco_ios("") == []
    assert _extract_route_maps_cisco_ios("interface Gi0/1\n ip address 1.1.1.1\n") == []


def test_extract_route_maps_preserves_body_text():
    """The body field should carry the verbatim stanza so downstream
    review tools can show the operator exactly what the router has."""
    from olav_netops.sim.network_model import _extract_route_maps_cisco_ios
    clauses = _extract_route_maps_cisco_ios(_SAMPLE_R1_CONFIG)
    body = clauses[0]["body"]
    assert body.startswith("route-map EXPORT_CUSTOMERS permit 10")
    assert "match ip address prefix-list CUST_PREFIXES" in body


# ── Layer accessors pins ────────────────────────────────────────────────


def test_l4_clauses_spans_both_devices(l4_db):
    m = load_network_model(db_path=l4_db)
    clauses = m.l4.clauses
    if not HAS_NETWORKX:
        assert clauses == []
        return
    # R1 has 3 stanzas, R2 has 1 → 4 total.
    assert len(clauses) == 4
    assert {c["device"] for c in clauses} == {"R1", "R2"}


def test_l4_devices_enumerates_hosts(l4_db):
    m = load_network_model(db_path=l4_db)
    if not HAS_NETWORKX:
        assert m.l4.devices() == []
        return
    assert m.l4.devices() == ["R1", "R2"]


def test_l4_policies_global_and_per_device(l4_db):
    m = load_network_model(db_path=l4_db)
    if not HAS_NETWORKX:
        assert m.l4.policies("R1") == []
        assert m.l4.policies("R2") == []
        assert m.l4.policies() == []
        return
    # Two distinct policy names across R1.
    assert m.l4.policies("R1") == ["EXPORT_CUSTOMERS", "IMPORT_INTERNET"]
    assert m.l4.policies("R2") == ["EXPORT_CUSTOMERS"]
    assert m.l4.policies() == ["EXPORT_CUSTOMERS", "IMPORT_INTERNET"]


def test_l4_by_device_orders_clauses_by_seq(l4_db):
    m = load_network_model(db_path=l4_db)
    r1 = m.l4.by_device("R1")
    if not HAS_NETWORKX:
        assert r1 == {}
        return
    assert set(r1.keys()) == {"EXPORT_CUSTOMERS", "IMPORT_INTERNET"}
    seqs = [c["seq"] for c in r1["EXPORT_CUSTOMERS"]]
    # Must be sorted ascending — seq 10 before seq 20.
    assert seqs == sorted(seqs)


def test_l4_by_policy_shortcut(l4_db):
    m = load_network_model(db_path=l4_db)
    clauses = m.l4.by_policy("R1", "EXPORT_CUSTOMERS")
    if not HAS_NETWORKX:
        assert clauses == []
        return
    assert len(clauses) == 2
    assert clauses[0]["action"] == "permit"
    assert clauses[1]["action"] == "deny"


def test_l4_graph_namespaces_policy_nodes(l4_db):
    m = load_network_model(db_path=l4_db)
    g = m.l4.graph
    if not HAS_NETWORKX:
        assert g is None
        return
    policy_nodes = [n for n in g.nodes if str(n).startswith("POLICY:")]
    assert "POLICY:EXPORT_CUSTOMERS" in policy_nodes
    assert "POLICY:IMPORT_INTERNET" in policy_nodes
    # Bare policy names must not appear as nodes (collision-proofing).
    assert "EXPORT_CUSTOMERS" not in g.nodes


# ── P3 policy-evaluation contract pin ──────────────────────────────────


def test_l4_policy_method_real_returns_unbound_for_missing_peer():
    """Round 59 filled in ``.policy(device, neighbor, direction)``.
    When no route-map is bound to the peer the walker returns
    ``unbound=True`` + action="permit" (Cisco default), not a raise —
    pin that contract so future refactors don't flip back to raising."""
    m = load_network_model(db_path="/definitely/missing.duckdb")
    result = m.l4.policy(
        device="R1", neighbor="10.0.12.2", direction="out", matches={}
    )
    assert result["unbound"] is True
    assert result["action"] == "permit"
    assert result["sets"] == []
    assert result["policy_name"] is None


# ── Scope / snapshot / edge-case pins ───────────────────────────────────


def test_l4_scope_restricts_devices(l4_db):
    m = load_network_model(db_path=l4_db, scope=["R1"])
    if not HAS_NETWORKX:
        assert m.l4.clauses == []
        assert m.l4.devices() == []
        return
    assert all(c["device"] == "R1" for c in m.l4.clauses)
    assert m.l4.devices() == ["R1"]


def test_l4_snapshot_missing_returns_empty_layer(l4_db):
    m = load_network_model(db_path=l4_db, snapshot="snap_nonexistent")
    assert m.l4.clauses == []
    if not HAS_NETWORKX:
        assert m.l4.graph is None
    else:
        assert m.l4.graph is not None
        assert m.l4.graph.number_of_nodes() == 0


def test_l4_missing_db_graceful():
    m = load_network_model(db_path="/definitely/missing.duckdb")
    layer = m.l4
    assert layer.clauses == []
    assert layer.graph is None
    assert layer.by_device("R1") == {}
    assert layer.policies() == []


def test_l4_ignores_non_config_commands(l4_db):
    """The ``show version`` row in the fixture must not feed the
    parser; still 4 clauses, never 5."""
    m = load_network_model(db_path=l4_db)
    if not HAS_NETWORKX:
        assert m.l4.clauses == []
        return
    assert len(m.l4.clauses) == 4


def test_public_surface_exports_l4_layer():
    from olav_netops.sim import L4Layer
    assert L4Layer.__name__ == "L4Layer"


def test_l4_independent_of_other_layers(l4_db):
    """Touching l4 must not materialise l1/l2/l3."""
    m = load_network_model(db_path=l4_db)
    _ = m.l4
    assert m._physical is None
    assert m._l2 is None
    assert m.l3._ospf is None
    assert m.l3._bgp is None

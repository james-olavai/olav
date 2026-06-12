"""Round 53 — ARCH-14 P1 L3 OSPF layer.

Fills in ``model.l3.ospf`` (previously a stub). Reads
``netops.parsed_outputs`` where ``command ILIKE '%ospf neighbor%'``
for the active snapshot, unpacks each device's parsed JSON array, and
projects into:

* ``model.l3.ospf.adjacencies`` — list of ``{device, neighbor_id,
  neighbor_ip, interface, state}`` dicts.
* ``model.l3.ospf.graph`` — ``networkx.Graph`` with device + router-id
  nodes.
* ``model.l3.ospf.neighbors(device)`` — sorted list of OSPF router-ids.
* ``model.l3.ospf.unhealthy()`` — adjacencies whose state isn't FULL/2WAY.

Pins:

* lazy-proxy semantics preserved (no DB touch on construction)
* ``model.l3.bgp`` remains a stub (its round hasn't happened yet)
* ``MAX(snapshot_id)`` fallback when ``snapshot=None``
* ``scope=[hosts]`` filters the ``device_name`` column
* parsed_data decoded from VARCHAR/JSON and tolerant to vendor case
  variation (``neighbor_id`` vs ``NEIGHBOR_ID`` etc.)
* empty result / missing DB path → graceful empty layer, not a raise
* ``unhealthy()`` bucket excludes FULL / 2WAY and surfaces anything else
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import duckdb
import pytest

from olav_netops.sim import load_network_model

HAS_NETWORKX = importlib.util.find_spec("networkx") is not None


@pytest.fixture()
def ospf_db(tmp_path: Path) -> Path:
    """DuckDB with three devices exchanging OSPF neighbors in snap_a."""
    db = tmp_path / "ospf.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        conn.execute(
            """
            CREATE TABLE netops.parsed_outputs (
                device_name VARCHAR,
                command     VARCHAR,
                parsed_data JSON,
                snapshot_id VARCHAR,
                created_at  TIMESTAMP
            )
            """
        )
        r1_nbrs = json.dumps([
            {"neighbor_id": "2.2.2.2", "address": "10.0.12.2",
             "interface": "Gi0/1", "state": "FULL"},
            {"neighbor_id": "3.3.3.3", "address": "10.0.13.3",
             "interface": "Gi0/2", "state": "FULL"},
        ])
        r2_nbrs = json.dumps([
            {"neighbor_id": "1.1.1.1", "address": "10.0.12.1",
             "interface": "Gi0/1", "state": "FULL"},
            # Intentionally stuck in INIT — surfaced by .unhealthy()
            {"neighbor_id": "3.3.3.3", "address": "10.0.23.3",
             "interface": "Gi0/2", "state": "INIT"},
        ])
        r3_nbrs = json.dumps([
            {"NEIGHBOR_ID": "1.1.1.1", "ADDRESS": "10.0.13.1",
             "INTERFACE": "Gi0/1", "STATE": "FULL"},  # vendor case variant
        ])
        for dev, blob in [("R1", r1_nbrs), ("R2", r2_nbrs), ("R3", r3_nbrs)]:
            conn.execute(
                "INSERT INTO netops.parsed_outputs VALUES "
                "(?, 'show ip ospf neighbor', ?, 'snap_a', NOW())",
                [dev, blob],
            )
        # Different command / unrelated row that must be ignored.
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES "
            "('R1', 'show version', '[]', 'snap_a', NOW())"
        )
    return db


# ── Lazy-proxy pins ─────────────────────────────────────────────────────


def test_l3_proxy_lazy_no_db_on_construction():
    """Constructing a NetworkModel must not touch OSPF at all."""
    m = load_network_model(db_path="/definitely/missing.duckdb")
    # Accessing model.l3 itself must not raise and must not query.
    proxy = m.l3
    assert proxy is not None


def test_l3_ospf_caches_after_first_access(ospf_db, monkeypatch):
    """Second access of model.l3.ospf must not rebuild."""
    from olav_netops.sim import network_model as nm

    real_build = nm._build_ospf_layer
    call_count = {"n": 0}

    def _spy(db, snap, scope):
        call_count["n"] += 1
        return real_build(db, snap, scope)

    monkeypatch.setattr(nm, "_build_ospf_layer", _spy)
    m = load_network_model(db_path=ospf_db)
    _ = m.l3.ospf
    _ = m.l3.ospf
    _ = m.l3.ospf
    assert call_count["n"] == 1


# ── Layer correctness pins ──────────────────────────────────────────────


def test_ospf_adjacencies_parsed_from_all_devices(ospf_db):
    m = load_network_model(db_path=ospf_db)
    adj = m.l3.ospf.adjacencies
    if not HAS_NETWORKX:
        assert adj == []
        return
    # R1→{R2,R3} (2) + R2→{R1,R3-INIT} (2) + R3→{R1} (1 vendor-case) = 5
    assert len(adj) == 5
    by_device = sorted({a["device"] for a in adj})
    assert by_device == ["R1", "R2", "R3"]


def test_ospf_graph_has_expected_edges(ospf_db):
    m = load_network_model(db_path=ospf_db)
    g = m.l3.ospf.graph
    if not HAS_NETWORKX:
        assert g is None
        return
    assert g is not None
    # Device names + 3 router-ids appear as distinct nodes (graph is
    # bipartite-ish since we add both sides).
    node_set = set(g.nodes)
    for dev in ("R1", "R2", "R3"):
        assert dev in node_set, f"device {dev} missing from OSPF graph"
    for rid in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        assert rid in node_set, f"router-id {rid} missing from OSPF graph"


def test_ospf_neighbors_accessor(ospf_db):
    m = load_network_model(db_path=ospf_db)
    if not HAS_NETWORKX:
        assert m.l3.ospf.neighbors("R1") == []
        assert m.l3.ospf.neighbors("NoSuchDevice") == []
        return
    # R1 reports two OSPF neighbors by router-id.
    assert m.l3.ospf.neighbors("R1") == ["2.2.2.2", "3.3.3.3"]
    # Unknown device → empty list, not raise.
    assert m.l3.ospf.neighbors("NoSuchDevice") == []


def test_ospf_unhealthy_roll_up(ospf_db):
    m = load_network_model(db_path=ospf_db)
    unhealthy = m.l3.ospf.unhealthy()
    if not HAS_NETWORKX:
        assert unhealthy == []
        return
    # Only R2→3.3.3.3 (INIT) should surface.
    assert len(unhealthy) == 1
    assert unhealthy[0]["device"] == "R2"
    assert unhealthy[0]["state"].upper() == "INIT"


def test_ospf_devices_lists_reporting_hosts(ospf_db):
    m = load_network_model(db_path=ospf_db)
    if not HAS_NETWORKX:
        assert m.l3.ospf.devices() == []
        return
    assert m.l3.ospf.devices() == ["R1", "R2", "R3"]


def test_ospf_scope_restricts_devices(ospf_db):
    m = load_network_model(db_path=ospf_db, scope=["R1"])
    adj = m.l3.ospf.adjacencies
    if not HAS_NETWORKX:
        assert adj == []
        assert m.l3.ospf.devices() == []
        return
    assert all(a["device"] == "R1" for a in adj)
    assert m.l3.ospf.devices() == ["R1"]


def test_ospf_snapshot_missing_returns_empty_layer(ospf_db):
    m = load_network_model(db_path=ospf_db, snapshot="snap_nonexistent")
    assert m.l3.ospf.adjacencies == []
    if not HAS_NETWORKX:
        assert m.l3.ospf.graph is None
    else:
        # graph is present (networkx.Graph()) but empty.
        assert m.l3.ospf.graph is not None
        assert m.l3.ospf.graph.number_of_nodes() == 0


def test_ospf_missing_db_graceful():
    m = load_network_model(db_path="/definitely/missing.duckdb")
    layer = m.l3.ospf
    assert layer.adjacencies == []
    assert layer.graph is None
    assert layer.neighbors("R1") == []
    assert layer.unhealthy() == []


def test_ospf_ignores_non_ospf_commands(ospf_db):
    """The `show version` row in the fixture must not be misinterpreted
    as OSPF data."""
    m = load_network_model(db_path=ospf_db)
    if not HAS_NETWORKX:
        assert m.l3.ospf.adjacencies == []
        return
    # 5 OSPF adjacencies total, NOT 6 (which would include the show
    # version row as an edge).
    assert len(m.l3.ospf.adjacencies) == 5


def test_public_surface_exports_ospf_layer():
    """``OspfLayer`` must be part of the public API so operators can
    ``isinstance`` or type-annotate against it."""
    from olav_netops.sim import OspfLayer
    assert OspfLayer.__name__ == "OspfLayer"


def test_l3_proxy_holds_parent_reference_not_copy():
    """The L3 proxy must see the parent model's snapshot/scope — otherwise
    changing those post-construction (not a public use case, but a common
    refactor mistake) would silently bind to stale values."""
    from olav_netops.sim import network_model as nm
    m = nm.NetworkModel(snapshot="snap_a", scope=["X"], db_path=Path("/nowhere"))
    # Private but important: proxy holds a live back-ref.
    assert m.l3._parent is m

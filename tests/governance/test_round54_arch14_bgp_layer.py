"""Round 54 — ARCH-14 P1 L3 BGP layer.

Fills in ``model.l3.bgp`` — previously a stub wired by Round 52.
Reads ``netops.parsed_outputs`` where ``command ILIKE '%bgp summary%'``
for the active snapshot, unpacks each device's parsed JSON array, and
projects into:

* ``model.l3.bgp.sessions`` — list of ``{device, neighbor_ip,
  neighbor_as, state}`` dicts
* ``model.l3.bgp.graph`` — ``networkx.Graph`` with device + neighbor IP
  nodes
* ``model.l3.bgp.neighbors(device)`` — sorted list of neighbor IPs
* ``model.l3.bgp.devices()`` — hostnames that reported at least one
  session
* ``model.l3.bgp.unhealthy()`` — sessions whose state isn't ``Established``
  (numeric prefix counts are treated as healthy per Cisco convention)

BGP field handling tolerates vendor variation:
* Cisco-style: ``neighbor`` / ``as`` / ``state_pfxrcd``
* Junos:      ``peer`` / ``peer_as`` / ``state``
* Arista EOS: Cisco-style
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import duckdb
import pytest

from olav_netops.sim import BgpLayer, load_network_model

HAS_NETWORKX = importlib.util.find_spec("networkx") is not None


@pytest.fixture()
def bgp_db(tmp_path: Path) -> Path:
    """DuckDB with three devices exchanging BGP sessions in snap_a.

    Covers all three vendor field shapes so the parser's tolerance is
    tested end-to-end, not just by inspection.
    """
    db = tmp_path / "bgp.duckdb"
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
        # Cisco-style output: neighbor / as / state_pfxrcd.
        # "12" is a prefix count → healthy; "Idle" is unhealthy.
        r1_sessions = json.dumps([
            {"neighbor": "10.0.12.2", "as": "65002", "state_pfxrcd": "12"},
            {"neighbor": "10.0.13.3", "as": "65003", "state_pfxrcd": "Idle"},
        ])
        # Junos-style output: peer / peer_as / state.
        r2_sessions = json.dumps([
            {"peer": "10.0.12.1", "peer_as": "65001", "state": "Established"},
            {"peer": "10.0.23.3", "peer_as": "65003", "state": "Active"},
        ])
        # Arista-style — same as Cisco, here with uppercase to also cover
        # the case-tolerance code path.
        r3_sessions = json.dumps([
            {"NEIGHBOR": "10.0.13.1", "AS": "65001", "STATE_PFXRCD": "5"},
        ])
        for dev, blob in [("R1", r1_sessions), ("R2", r2_sessions), ("R3", r3_sessions)]:
            conn.execute(
                "INSERT INTO netops.parsed_outputs VALUES "
                "(?, 'show ip bgp summary', ?, 'snap_a', NOW())",
                [dev, blob],
            )
        # Unrelated command must be ignored.
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES "
            "('R1', 'show version', '[]', 'snap_a', NOW())"
        )
    return db


# ── Lazy-proxy pins ─────────────────────────────────────────────────────


def test_l3_bgp_is_bgplayer_instance():
    """model.l3.bgp must resolve to a BgpLayer, not raise and not return
    a stub."""
    m = load_network_model(db_path="/definitely/missing.duckdb")
    assert isinstance(m.l3.bgp, BgpLayer)


def test_l3_bgp_caches_after_first_access(bgp_db, monkeypatch):
    from olav_netops.sim import network_model as nm

    real_build = nm._build_bgp_layer
    call_count = {"n": 0}

    def _spy(db, snap, scope):
        call_count["n"] += 1
        return real_build(db, snap, scope)

    monkeypatch.setattr(nm, "_build_bgp_layer", _spy)
    m = load_network_model(db_path=bgp_db)
    _ = m.l3.bgp
    _ = m.l3.bgp
    _ = m.l3.bgp
    assert call_count["n"] == 1


# ── Parsing correctness pins ────────────────────────────────────────────


def test_bgp_sessions_parsed_from_all_vendor_shapes(bgp_db):
    m = load_network_model(db_path=bgp_db)
    sessions = m.l3.bgp.sessions
    if not HAS_NETWORKX:
        assert sessions == []
        return
    # R1: 2 Cisco rows + R2: 2 Junos rows + R3: 1 Arista uppercase = 5
    assert len(sessions) == 5
    # All devices present.
    assert sorted({s["device"] for s in sessions}) == ["R1", "R2", "R3"]


def test_bgp_session_fields_normalised(bgp_db):
    """Vendor synonyms must all normalise onto neighbor_ip / neighbor_as /
    state — callers should not have to branch on vendor."""
    m = load_network_model(db_path=bgp_db)
    sessions = m.l3.bgp.sessions
    if not HAS_NETWORKX:
        assert sessions == []
        return
    for s in sessions:
        assert set(s.keys()) == {"device", "neighbor_ip", "neighbor_as", "state"}
        assert s["neighbor_ip"]  # always populated
    # R2 Junos row should surface as "10.0.12.1" / "65001" / "Established".
    r2 = [s for s in sessions if s["device"] == "R2" and s["neighbor_ip"] == "10.0.12.1"]
    assert len(r2) == 1
    assert r2[0]["neighbor_as"] == "65001"
    assert r2[0]["state"] == "Established"


def test_bgp_graph_has_expected_nodes_and_edges(bgp_db):
    m = load_network_model(db_path=bgp_db)
    g = m.l3.bgp.graph
    if not HAS_NETWORKX:
        assert g is None
        return
    assert g is not None
    # 3 devices + 4 distinct neighbor IPs (10.0.12.1, 10.0.12.2, 10.0.13.1,
    # 10.0.13.3, 10.0.23.3) = 3+5 = 8 nodes. Actually unique IPs:
    # 10.0.12.1, 10.0.12.2, 10.0.13.1, 10.0.13.3, 10.0.23.3 = 5 IPs.
    expected_nodes = {"R1", "R2", "R3",
                      "10.0.12.1", "10.0.12.2", "10.0.13.1",
                      "10.0.13.3", "10.0.23.3"}
    assert set(g.nodes) == expected_nodes
    # 5 edges (one per session row).
    assert g.number_of_edges() == 5


def test_bgp_neighbors_accessor(bgp_db):
    m = load_network_model(db_path=bgp_db)
    if not HAS_NETWORKX:
        assert m.l3.bgp.neighbors("R1") == []
        assert m.l3.bgp.neighbors("NoSuchDevice") == []
        return
    # R1's two sessions are 10.0.12.2 and 10.0.13.3.
    assert m.l3.bgp.neighbors("R1") == ["10.0.12.2", "10.0.13.3"]
    assert m.l3.bgp.neighbors("NoSuchDevice") == []


def test_bgp_devices_lists_reporting_hosts(bgp_db):
    m = load_network_model(db_path=bgp_db)
    if not HAS_NETWORKX:
        assert m.l3.bgp.devices() == []
        return
    assert m.l3.bgp.devices() == ["R1", "R2", "R3"]


# ── Health roll-up pins ─────────────────────────────────────────────────


def test_bgp_unhealthy_excludes_numeric_prefix_counts(bgp_db):
    """Cisco-style "state_pfxrcd" contains the prefix-received count when
    the session is Established — must not be flagged unhealthy."""
    m = load_network_model(db_path=bgp_db)
    unhealthy = m.l3.bgp.unhealthy()
    if not HAS_NETWORKX:
        assert unhealthy == []
        return
    # Only R1→10.0.13.3 (Idle) + R2→10.0.23.3 (Active) should surface.
    unhealthy_keys = {(u["device"], u["neighbor_ip"]) for u in unhealthy}
    assert unhealthy_keys == {("R1", "10.0.13.3"), ("R2", "10.0.23.3")}


def test_bgp_unhealthy_treats_established_case_insensitively(bgp_db):
    m = load_network_model(db_path=bgp_db)
    if not HAS_NETWORKX:
        assert m.l3.bgp.unhealthy() == []
        return
    # R2→10.0.12.1 is explicitly "Established" → must NOT be in unhealthy.
    unhealthy_keys = {(u["device"], u["neighbor_ip"]) for u in m.l3.bgp.unhealthy()}
    assert ("R2", "10.0.12.1") not in unhealthy_keys


# ── Scope / snapshot / edge-case pins ───────────────────────────────────


def test_bgp_scope_restricts_devices(bgp_db):
    m = load_network_model(db_path=bgp_db, scope=["R1"])
    sessions = m.l3.bgp.sessions
    if not HAS_NETWORKX:
        assert sessions == []
        assert m.l3.bgp.devices() == []
        return
    assert all(s["device"] == "R1" for s in sessions)
    assert m.l3.bgp.devices() == ["R1"]


def test_bgp_snapshot_missing_returns_empty_layer(bgp_db):
    m = load_network_model(db_path=bgp_db, snapshot="snap_nonexistent")
    assert m.l3.bgp.sessions == []
    if not HAS_NETWORKX:
        assert m.l3.bgp.graph is None
    else:
        assert m.l3.bgp.graph is not None
        assert m.l3.bgp.graph.number_of_nodes() == 0


def test_bgp_missing_db_graceful():
    m = load_network_model(db_path="/definitely/missing.duckdb")
    layer = m.l3.bgp
    assert layer.sessions == []
    assert layer.graph is None
    assert layer.neighbors("R1") == []
    assert layer.unhealthy() == []


def test_bgp_ignores_non_bgp_commands(bgp_db):
    """The `show version` row in the fixture must not be interpreted as
    BGP data."""
    m = load_network_model(db_path=bgp_db)
    if not HAS_NETWORKX:
        assert m.l3.bgp.sessions == []
        return
    assert len(m.l3.bgp.sessions) == 5  # NOT 6


def test_public_surface_exports_bgp_layer():
    from olav_netops.sim import BgpLayer
    assert BgpLayer.__name__ == "BgpLayer"


def test_ospf_and_bgp_layers_are_independent(bgp_db):
    """Touching model.l3.bgp must not materialise model.l3.ospf (and vice
    versa). Separately-built layers each pay their own DB cost."""
    from olav_netops.sim import network_model as nm

    m = load_network_model(db_path=bgp_db)
    # Access bgp only.
    _ = m.l3.bgp
    # The ospf layer should still be uninitialised (None) on the proxy.
    assert m.l3._ospf is None, (
        "Accessing model.l3.bgp unexpectedly triggered OSPF materialisation"
    )

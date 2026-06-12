"""Round 55 — ARCH-14 P1 L2 VLAN layer.

Fills in ``model.l2`` — previously a stub wired by Round 52.
Reads ``netops.parsed_outputs`` where ``command ILIKE '%vlan%'`` for
the active snapshot, normalises Cisco / Junos / mixed-case field
shapes, and projects into:

* ``model.l2.vlans`` — list of ``{device, vlan_id, name, interfaces}``
* ``model.l2.graph`` — ``networkx.Graph`` with devices + namespaced
  ``VLAN:<id>`` nodes (namespacing prevents hostname/id collision)
* ``model.l2.by_device(device)`` — ``{vlan_id: [interfaces]}``
* ``model.l2.vlan_ids(device=None)`` — sorted ids (all or per-device)
* ``model.l2.devices()`` — hostnames reporting at least one VLAN

Interface lists are normalised — Cisco returns arrays, Junos sometimes
returns comma- or space-separated strings; callers always see ``list[str]``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import duckdb
import pytest

from olav_netops.sim import L2Layer, load_network_model

HAS_NETWORKX = importlib.util.find_spec("networkx") is not None


@pytest.fixture()
def l2_db(tmp_path: Path) -> Path:
    """DuckDB with three devices reporting VLANs in snap_a. Covers
    Cisco list-of-dicts, Junos alternate field names, mixed case, and
    comma-separated interface strings."""
    db = tmp_path / "l2.duckdb"
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
        r1_vlans = json.dumps([
            {"vlan_id": "10", "name": "data",
             "interfaces": ["Gi0/1", "Gi0/2"]},
            {"vlan_id": "20", "name": "voice",
             "interfaces": ["Gi0/3"]},
        ])
        # Junos style: vlan_name / tag / comma-separated interfaces.
        r2_vlans = json.dumps([
            {"vlan_name": "data", "tag": "10",
             "interfaces": "ge-0/0/0.0, ge-0/0/1.0"},
            {"vlan_name": "mgmt", "tag": "99",
             "interfaces": "ge-0/0/2.0"},
        ])
        # Uppercase variant.
        r3_vlans = json.dumps([
            {"VLAN_ID": "10", "NAME": "data",
             "INTERFACES": ["Ethernet1"]},
        ])
        for dev, blob in [("R1", r1_vlans), ("R2", r2_vlans), ("R3", r3_vlans)]:
            conn.execute(
                "INSERT INTO netops.parsed_outputs VALUES "
                "(?, 'show vlan brief', ?, 'snap_a', NOW())",
                [dev, blob],
            )
        # Non-VLAN command that must be ignored.
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES "
            "('R1', 'show version', '[]', 'snap_a', NOW())"
        )
    return db


# ── Lazy-proxy pins ─────────────────────────────────────────────────────


def test_l2_is_l2layer_instance():
    m = load_network_model(db_path="/definitely/missing.duckdb")
    assert isinstance(m.l2, L2Layer)


def test_l2_caches_after_first_access(l2_db, monkeypatch):
    from olav_netops.sim import network_model as nm

    real_build = nm._build_l2_layer
    call_count = {"n": 0}

    def _spy(db, snap, scope):
        call_count["n"] += 1
        return real_build(db, snap, scope)

    monkeypatch.setattr(nm, "_build_l2_layer", _spy)
    m = load_network_model(db_path=l2_db)
    _ = m.l2
    _ = m.l2
    _ = m.l2
    assert call_count["n"] == 1


# ── Parsing correctness pins ────────────────────────────────────────────


def test_l2_vlans_parsed_from_all_vendor_shapes(l2_db):
    m = load_network_model(db_path=l2_db)
    vlans = m.l2.vlans
    if not HAS_NETWORKX:
        assert vlans == []
        return
    # R1: 2 Cisco + R2: 2 Junos + R3: 1 uppercase = 5
    assert len(vlans) == 5
    assert sorted({v["device"] for v in vlans}) == ["R1", "R2", "R3"]


def test_l2_field_normalisation(l2_db):
    m = load_network_model(db_path=l2_db)
    for v in m.l2.vlans:
        assert set(v.keys()) == {"device", "vlan_id", "name", "interfaces"}
        assert isinstance(v["interfaces"], list)
        for iface in v["interfaces"]:
            assert isinstance(iface, str)
            assert iface  # non-empty


def test_l2_junos_interface_string_is_split(l2_db):
    """Junos returns "ge-0/0/0.0, ge-0/0/1.0" as a single string — the
    normaliser must split on comma/whitespace into a list."""
    m = load_network_model(db_path=l2_db)
    if not HAS_NETWORKX:
        assert m.l2.vlans == []
        return
    r2_data_vlan = [
        v for v in m.l2.vlans
        if v["device"] == "R2" and v["vlan_id"] == "10"
    ]
    assert len(r2_data_vlan) == 1
    assert r2_data_vlan[0]["interfaces"] == ["ge-0/0/0.0", "ge-0/0/1.0"]


def test_l2_by_device_accessor(l2_db):
    m = load_network_model(db_path=l2_db)
    if not HAS_NETWORKX:
        assert m.l2.by_device("R1") == {}
        assert m.l2.by_device("NoSuchDevice") == {}
        return
    r1 = m.l2.by_device("R1")
    assert r1 == {
        "10": ["Gi0/1", "Gi0/2"],
        "20": ["Gi0/3"],
    }
    # Unknown device → empty dict, not raise.
    assert m.l2.by_device("NoSuchDevice") == {}


def test_l2_vlan_ids_global_and_per_device(l2_db):
    m = load_network_model(db_path=l2_db)
    if not HAS_NETWORKX:
        assert m.l2.vlan_ids() == []
        assert m.l2.vlan_ids("R1") == []
        assert m.l2.vlan_ids("R2") == []
        assert m.l2.vlan_ids("NoSuchDevice") == []
        return
    all_ids = m.l2.vlan_ids()
    # Distinct vlan_ids across fixture: 10, 20, 99 (sort ascending).
    assert all_ids == ["10", "20", "99"]
    # Per-device scoping.
    assert m.l2.vlan_ids("R1") == ["10", "20"]
    assert m.l2.vlan_ids("R2") == ["10", "99"]
    assert m.l2.vlan_ids("NoSuchDevice") == []


def test_l2_devices_lists_reporting_hosts(l2_db):
    m = load_network_model(db_path=l2_db)
    if not HAS_NETWORKX:
        assert m.l2.devices() == []
        return
    assert m.l2.devices() == ["R1", "R2", "R3"]


def test_l2_graph_namespaces_vlan_nodes(l2_db):
    """VLAN nodes must be prefixed ``VLAN:`` so they can't collide with
    hostnames like ``10`` or ``99`` in unusual deployments."""
    m = load_network_model(db_path=l2_db)
    g = m.l2.graph
    if not HAS_NETWORKX:
        assert g is None
        return
    vlan_nodes = [n for n in g.nodes if str(n).startswith("VLAN:")]
    assert set(vlan_nodes) == {"VLAN:10", "VLAN:20", "VLAN:99"}
    # No bare int/str id collides with the device side.
    assert "10" not in g.nodes
    assert "99" not in g.nodes


# ── Scope / snapshot / edge-case pins ───────────────────────────────────


def test_l2_scope_restricts_devices(l2_db):
    m = load_network_model(db_path=l2_db, scope=["R1"])
    if not HAS_NETWORKX:
        assert m.l2.vlans == []
        assert m.l2.devices() == []
        return
    assert all(v["device"] == "R1" for v in m.l2.vlans)
    assert m.l2.devices() == ["R1"]


def test_l2_snapshot_missing_returns_empty_layer(l2_db):
    m = load_network_model(db_path=l2_db, snapshot="snap_nonexistent")
    assert m.l2.vlans == []
    if not HAS_NETWORKX:
        assert m.l2.graph is None
    else:
        assert m.l2.graph is not None
        assert m.l2.graph.number_of_nodes() == 0


def test_l2_missing_db_graceful():
    m = load_network_model(db_path="/definitely/missing.duckdb")
    layer = m.l2
    assert layer.vlans == []
    assert layer.graph is None
    assert layer.by_device("R1") == {}
    assert layer.vlan_ids() == []


def test_l2_ignores_non_vlan_commands(l2_db):
    """The `show version` row must not be interpreted as a VLAN row."""
    m = load_network_model(db_path=l2_db)
    if not HAS_NETWORKX:
        assert m.l2.vlans == []
        return
    assert len(m.l2.vlans) == 5  # NOT 6


def test_public_surface_exports_l2_layer():
    from olav_netops.sim import L2Layer
    assert L2Layer.__name__ == "L2Layer"


def test_interface_list_normaliser_public_smoke():
    """The helper must handle list / string / None / mixed input — pin
    directly to lock behaviour since layers delegate to it."""
    from olav_netops.sim.network_model import _normalise_interface_list
    assert _normalise_interface_list(None) == []
    assert _normalise_interface_list([]) == []
    assert _normalise_interface_list(["Gi0/1", "Gi0/2"]) == ["Gi0/1", "Gi0/2"]
    # Strings with empties stripped.
    assert _normalise_interface_list("a, b,,c") == ["a", "b", "c"]
    # Space-separated Junos bundle.
    assert _normalise_interface_list("ge-0/0/0 ge-0/0/1") == ["ge-0/0/0", "ge-0/0/1"]
    # Objects that aren't list/str → empty list, not raise.
    assert _normalise_interface_list(42) == []


def test_l2_independent_of_other_layers(l2_db):
    """Touching model.l2 must not trigger physical/l3 materialisation."""
    m = load_network_model(db_path=l2_db)
    _ = m.l2
    assert m._physical is None
    # L3 proxy still has no materialised sub-layers.
    assert m.l3._ospf is None
    assert m.l3._bgp is None

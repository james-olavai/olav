"""Unit tests for sim.graph_view — model.graph + model.facts helpers.

Use mocked DuckDB connection so tests don't depend on demo7 fixtures.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from olav_netops.sim.graph_view import build_device_facts, build_unified_graph


def _mock_duckdb(connect_factory):
    """Patch duckdb.connect with a custom factory."""
    return patch("duckdb.connect", side_effect=connect_factory)


def _make_conn(query_results: dict[str, list]):
    """Mock duckdb connection that returns canned results per SQL prefix."""
    conn = MagicMock()
    def execute(sql, params=None):
        cur = MagicMock()
        for prefix, rows in query_results.items():
            if prefix in sql:
                cur.fetchall.return_value = rows
                cur.fetchone.return_value = rows[0] if rows else (None,)
                return cur
        cur.fetchall.return_value = []
        cur.fetchone.return_value = (None,)
        return cur
    conn.execute = execute
    conn.close = MagicMock()
    return conn


def test_facts_consolidates_metadata_loopback():
    """Loopback from devices.metadata is preferred."""
    query_results = {
        "FROM netops.devices": [
            ("R1", "juniper_junos", "192.168.1.1", "border",
             '{"loopback_ip": "1.1.1.1"}'),
        ],
        "FROM netops.v_show_ip_bgp_summary_auto": [],
        "MAX(snapshot_id)": [(None,)],
    }
    with _mock_duckdb(lambda *a, **k: _make_conn(query_results)):
        facts = build_device_facts(db_path="/fake")
    assert facts["R1"]["loopback"] == "1.1.1.1"
    assert facts["R1"]["platform"] == "juniper_junos"
    assert facts["R1"]["mgmt_ip"] == "192.168.1.1"
    assert facts["R1"]["role"] == "border"


def test_facts_loopback_from_bgp_router_id_when_metadata_empty():
    """router_id from BGP summary view fills in when metadata is empty."""
    query_results = {
        "FROM netops.devices": [
            ("R3", "cisco_ios", "192.168.1.3", "core", "{}"),
        ],
        "FROM netops.v_show_ip_bgp_summary_auto": [
            ("R3", "3.3.3.3", 65000),
        ],
    }
    with _mock_duckdb(lambda *a, **k: _make_conn(query_results)):
        facts = build_device_facts(db_path="/fake")
    assert facts["R3"]["loopback"] == "3.3.3.3"
    assert facts["R3"]["local_as"] == 65000


def test_facts_cross_resolve_for_junos_via_known_loopback():
    """Junos R1 doesn't appear in Cisco BGP view as device_name, but its
    loopback (1.1.1.1) appears as a peer's bgp_neighbor — cross-resolve.
    """
    query_results = {
        "FROM netops.devices": [
            ("R1", "juniper_junos", "192.168.1.1", "border",
             '{"loopback_ip": "1.1.1.1"}'),
            ("R3", "cisco_ios", "192.168.1.3", "core",
             '{"loopback_ip": "3.3.3.3"}'),
        ],
        # Note: this list is queried twice — once for ASN/router_id
        # (filtered by local_as IS NOT NULL), once for cross-resolve.
        "FROM netops.v_show_ip_bgp_summary_auto": [
            ("R3", "3.3.3.3", 65000),         # R3 → its own row
            ("R3", "1.1.1.1", 65000),         # R3 sees R1 as iBGP neighbour (cross)
        ],
    }
    # Mock returns identical rows; relies on graph_view filtering correctly
    with _mock_duckdb(lambda *a, **k: _make_conn(query_results)):
        facts = build_device_facts(db_path="/fake")
    # R3 from own row
    assert facts["R3"]["local_as"] == 65000
    # R1's local_as inferred via cross-resolve (R3 sees 1.1.1.1=R1's loopback
    # with neighbor_as=65000).
    assert facts["R1"]["local_as"] == 65000


def test_facts_does_not_misattribute_to_access_switch():
    """Access switch SW1 with no loopback should NOT inherit a router's
    loopback (regression test for the over-aggressive heuristic).
    """
    query_results = {
        "FROM netops.devices": [
            ("R3", "cisco_ios", "192.168.1.3", "core",
             '{"loopback_ip": "3.3.3.3"}'),
            ("SW1", "cisco_ios", "192.168.1.5", "access", "{}"),
        ],
        "FROM netops.v_show_ip_bgp_summary_auto": [
            ("R3", "3.3.3.3", 65000),
            ("R3", "10.1.99.1", 65001),  # unmatched neighbour
        ],
    }
    with _mock_duckdb(lambda *a, **k: _make_conn(query_results)):
        facts = build_device_facts(db_path="/fake")
    # R3 resolved
    assert facts["R3"]["loopback"] == "3.3.3.3"
    # SW1 stays unresolved — role 'access' excludes from heuristic
    assert facts["SW1"]["loopback"] is None
    assert facts["SW1"]["local_as"] is None


def test_unified_graph_loads_l2_topology():
    """L2 edges from topology_links populate the DiGraph (both directions)."""
    query_results = {
        "FROM netops.devices": [
            ("R1", "juniper_junos", "192.168.1.1", "border", "{}"),
            ("R3", "cisco_ios", "192.168.1.3", "core",
             '{"loopback_ip": "3.3.3.3"}'),
        ],
        "FROM netops.v_show_ip_bgp_summary_auto": [],
        "FROM netops.v_show_ip_ospf_neighbor_auto": [],
        "FROM netops.topology_links": [
            ("R1", "ge-0/0/2", "R3", "Eth0/0", "LLDP", "up"),
        ],
        "MAX(snapshot_id)": [("snap1",)],
    }
    with _mock_duckdb(lambda *a, **k: _make_conn(query_results)):
        g = build_unified_graph(db_path="/fake")
    assert g.has_edge("R1", "R3")
    assert g.has_edge("R3", "R1")  # mirror
    assert g["R1"]["R3"]["layer"] == "L2"
    assert g["R1"]["R3"]["link_status"] == "up"


def test_unified_graph_node_attrs_consolidate_facts():
    """DiGraph node attrs include the device facts."""
    query_results = {
        "FROM netops.devices": [
            ("R1", "juniper_junos", "192.168.1.1", "border",
             '{"loopback_ip": "1.1.1.1"}'),
        ],
        "FROM netops.v_show_ip_bgp_summary_auto": [],
        "FROM netops.topology_links": [],
        "MAX(snapshot_id)": [("snap1",)],
    }
    with _mock_duckdb(lambda *a, **k: _make_conn(query_results)):
        g = build_unified_graph(db_path="/fake")
    assert "R1" in g.nodes
    assert g.nodes["R1"]["platform"] == "juniper_junos"
    assert g.nodes["R1"]["loopback"] == "1.1.1.1"


def test_unified_graph_supports_what_if_node_removal():
    """Standard NetworkX operations (copy + remove_node) work."""
    import networkx as nx
    query_results = {
        "FROM netops.devices": [
            ("R1", "junos", "1.1.1.1", "border", "{}"),
            ("R2", "ios", "2.2.2.2", "core", "{}"),
            ("R3", "ios", "3.3.3.3", "core", "{}"),
        ],
        "FROM netops.v_show_ip_bgp_summary_auto": [],
        "FROM netops.topology_links": [
            ("R1", "i1", "R2", "i2", "LLDP", "up"),
            ("R2", "i3", "R3", "i4", "LLDP", "up"),
        ],
        "MAX(snapshot_id)": [("snap1",)],
    }
    with _mock_duckdb(lambda *a, **k: _make_conn(query_results)):
        g = build_unified_graph(db_path="/fake")
    g_post = g.copy()
    g_post.remove_node("R2")
    # Without R2, R1 and R3 are disconnected
    assert not nx.has_path(g_post, "R1", "R3")
    # Original unchanged
    assert nx.has_path(g, "R1", "R3")

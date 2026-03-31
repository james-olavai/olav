"""Unit tests for Phase 5 Ops NetworkX Sandbox.

All tests use in-memory ControlPlaneSnapshot — no real DuckDB required.
Coverage:
  - GraphBuilder: node count, edge count, attributes
  - StateProjector: BGP/OSPF/STP/IS-IS/EVPN/VXLAN/MPLS projection
  - OSPF cost: edge weight, find_shortest_path uses cost
  - STP: port role/state attached to nodes
  - IS-IS: adjacency attached to nodes
  - EVPN/VXLAN/MPLS: instances/tunnels/peers attached to nodes
  - get_blast_radius: known device, unknown device, neighbor set
  - find_shortest_path: direct link, multi-hop, no path, unknown device
  - test_hypothesis: device_down, link_down, bgp_session_down, unknown type
  - Hallucination guard: invented devices / links rejected
"""

import pytest
from olav.core.control_plane_ir import (
    BGPNeighbor,
    ControlPlaneSnapshot,
    Device,
    EVPNInstance,
    ISISAdjacency,
    MPLSLDPPeer,
    OSPFNeighbor,
    Route,
    STPPort,
    TopologyLink,
    VXLANTunnel,
)
from olav.core.sandbox import GraphBuilder, OpsNetworkXSandbox, StateProjector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_snapshot() -> ControlPlaneSnapshot:
    """
    Topology:
        R1 -- R2 (LLDP, L3)
        R2 -- R3 (LLDP, L3)
        R1 -- R3 (BGP, L3)   ← alternate path R1→R3

    BGP: R1↔R3 (Established), R2↔R3 (Idle)
    OSPF: R1↔R2 adj on Gi0/0 (Full), R2↔R3 adj on Gi0/1 (Full)
    """
    devices = [
        Device(name="R1", mgmt_ip="192.168.1.1", platform="IOS-XE"),
        Device(name="R2", mgmt_ip="192.168.1.2", platform="IOS-XE"),
        Device(name="R3", mgmt_ip="192.168.1.3", platform="IOS-XR"),
    ]
    topology_links = [
        TopologyLink(source="R1", target="R2", source_iface="Gi0/0", target_iface="Gi0/0", protocol="LLDP", link_type="L3"),
        TopologyLink(source="R2", target="R1", source_iface="Gi0/0", target_iface="Gi0/0", protocol="LLDP", link_type="L3"),
        TopologyLink(source="R2", target="R3", source_iface="Gi0/1", target_iface="Gi0/0", protocol="LLDP", link_type="L3"),
        TopologyLink(source="R3", target="R2", source_iface="Gi0/0", target_iface="Gi0/1", protocol="LLDP", link_type="L3"),
        TopologyLink(source="R1", target="R3", source_iface="Gi0/1", target_iface="Gi0/1", protocol="BGP", link_type="L3"),
        TopologyLink(source="R3", target="R1", source_iface="Gi0/1", target_iface="Gi0/1", protocol="BGP", link_type="L3"),
    ]
    bgp_neighbors = [
        BGPNeighbor(device="R1", peer_ip="192.168.1.3", peer_as="65003", state="Established"),
        BGPNeighbor(device="R3", peer_ip="192.168.1.1", peer_as="65001", state="Established"),
        BGPNeighbor(device="R2", peer_ip="192.168.1.3", peer_as="65003", state="Idle"),
    ]
    ospf_neighbors = [
        OSPFNeighbor(device="R1", neighbor_id="2.2.2.2", neighbor_ip="10.0.12.2", interface="Gi0/0", state="Full", cost=10),
        OSPFNeighbor(device="R2", neighbor_id="1.1.1.1", neighbor_ip="10.0.12.1", interface="Gi0/0", state="Full", cost=10),
        OSPFNeighbor(device="R2", neighbor_id="3.3.3.3", neighbor_ip="10.0.23.3", interface="Gi0/1", state="Full", cost=100),
        OSPFNeighbor(device="R3", neighbor_id="2.2.2.2", neighbor_ip="10.0.23.2", interface="Gi0/0", state="Full", cost=100),
    ]
    routes = [
        Route(device="R1", network="10.0.0.0/8", next_hop="192.168.1.2", protocol="OSPF"),
    ]
    stp_ports = [
        STPPort(device="R1", interface="Gi0/0", role="Root", state="FWD", vlan_id="1", cost=100),
        STPPort(device="R1", interface="Gi0/1", role="Desg", state="FWD", vlan_id="1", cost=100),
        STPPort(device="R2", interface="Gi0/0", role="Desg", state="FWD", vlan_id="1", cost=100),
        STPPort(device="R2", interface="Gi0/1", role="Altn", state="BLK", vlan_id="1", cost=100),
    ]
    isis_adjacencies = [
        ISISAdjacency(device="R1", system_id="0000.0000.0002", interface="Gi0/0", state="Up", level="L2"),
        ISISAdjacency(device="R2", system_id="0000.0000.0001", interface="Gi0/0", state="Up", level="L2"),
    ]
    evpn_instances = [
        EVPNInstance(device="R1", evi="10", vni="10010", rd="1.1.1.1:10", type="L2"),
    ]
    vxlan_tunnels = [
        VXLANTunnel(device="R1", vni="10010", local_vtep="192.168.1.1", remote_vtep="192.168.1.3"),
    ]
    mpls_ldp_peers = [
        MPLSLDPPeer(device="R1", ldp_peer="192.168.1.2", transport_addr="192.168.1.1", state="Oper"),
    ]
    return ControlPlaneSnapshot(
        devices=devices,
        bgp_neighbors=bgp_neighbors,
        routes=routes,
        ospf_neighbors=ospf_neighbors,
        topology_links=topology_links,
        stp_ports=stp_ports,
        isis_adjacencies=isis_adjacencies,
        evpn_instances=evpn_instances,
        vxlan_tunnels=vxlan_tunnels,
        mpls_ldp_peers=mpls_ldp_peers,
    )


@pytest.fixture
def snapshot():
    return _make_snapshot()


@pytest.fixture
def sandbox(snapshot):
    return OpsNetworkXSandbox(snapshot)


# ---------------------------------------------------------------------------
# Layer 1 — GraphBuilder
# ---------------------------------------------------------------------------


class TestGraphBuilder:
    def test_node_count_equals_device_count(self, snapshot):
        G = GraphBuilder().build(snapshot)
        assert G.number_of_nodes() == len(snapshot.devices)

    def test_edge_count_equals_topology_links(self, snapshot):
        G = GraphBuilder().build(snapshot)
        assert G.number_of_edges() == len(snapshot.topology_links)

    def test_node_has_platform_attribute(self, snapshot):
        G = GraphBuilder().build(snapshot)
        assert G.nodes["R1"]["platform"] == "IOS-XE"
        assert G.nodes["R3"]["platform"] == "IOS-XR"

    def test_node_has_mgmt_ip(self, snapshot):
        G = GraphBuilder().build(snapshot)
        assert G.nodes["R2"]["mgmt_ip"] == "192.168.1.2"

    def test_edge_has_rel_type_topology(self, snapshot):
        G = GraphBuilder().build(snapshot)
        # At least one edge R1→R2 should exist
        edges = list(G.edges("R1", data=True))
        assert any(d.get("rel_type") == "topology" for _, _, d in edges)

    def test_topology_only_device_auto_added_as_node(self):
        """Device in topology_links but not in devices table should still be a node."""
        snap = ControlPlaneSnapshot(
            devices=[Device(name="R1")],
            topology_links=[TopologyLink(source="R1", target="R99")],
        )
        G = GraphBuilder().build(snap)
        assert "R99" in G.nodes()


# ---------------------------------------------------------------------------
# Layer 2 — StateProjector
# ---------------------------------------------------------------------------


class TestStateProjector:
    def test_bgp_session_attached_to_node(self, snapshot):
        G = GraphBuilder().build(snapshot)
        StateProjector().project(G, snapshot)
        sessions = G.nodes["R1"]["bgp_sessions"]
        assert any(s["peer_ip"] == "192.168.1.3" for s in sessions)

    def test_bgp_state_preserved(self, snapshot):
        G = GraphBuilder().build(snapshot)
        StateProjector().project(G, snapshot)
        sessions = G.nodes["R1"]["bgp_sessions"]
        r1_to_r3 = next(s for s in sessions if s["peer_ip"] == "192.168.1.3")
        assert r1_to_r3["state"] == "Established"

    def test_ospf_adjacency_attached_to_node(self, snapshot):
        G = GraphBuilder().build(snapshot)
        StateProjector().project(G, snapshot)
        adjs = G.nodes["R2"]["ospf_adjacencies"]
        assert any(a["neighbor_id"] == "1.1.1.1" for a in adjs)

    def test_ospf_multiple_adjacencies(self, snapshot):
        G = GraphBuilder().build(snapshot)
        StateProjector().project(G, snapshot)
        # R2 has two OSPF adjacencies (R1 and R3)
        adjs = G.nodes["R2"]["ospf_adjacencies"]
        assert len(adjs) == 2

    def test_unknown_device_bgp_skipped_gracefully(self):
        snap = ControlPlaneSnapshot(
            devices=[Device(name="R1")],
            bgp_neighbors=[BGPNeighbor(device="GHOST", peer_ip="1.2.3.4", peer_as="65000", state="Idle")],
        )
        G = GraphBuilder().build(snap)
        # Should not raise
        StateProjector().project(G, snap)
        assert "GHOST" not in G.nodes()


# ---------------------------------------------------------------------------
# Layer 3 — get_blast_radius
# ---------------------------------------------------------------------------


class TestGetBlastRadius:
    def test_known_device_returns_result(self, sandbox):
        result = sandbox.get_blast_radius("R2")
        assert result["operation"] == "get_blast_radius"
        assert result["inputs"]["device"] == "R2"

    def test_r2_neighbors_include_r1_and_r3(self, sandbox):
        result = sandbox.get_blast_radius("R2")
        # direct_neighbors = only real devices (is_real_device=True)
        neighbors = result["result"]["direct_neighbors"]
        assert "R1" in neighbors
        assert "R3" in neighbors

    def test_r1_bgp_session_in_blast_radius(self, sandbox):
        result = sandbox.get_blast_radius("R1")
        bgp = result["result"]["affected_bgp_sessions"]
        assert any(s["peer_ip"] == "192.168.1.3" for s in bgp)

    def test_requires_clab_when_bgp_present(self, sandbox):
        result = sandbox.get_blast_radius("R1")
        assert result["requires_clab_validation"] is True

    def test_unknown_device_returns_error(self, sandbox):
        result = sandbox.get_blast_radius("DOES_NOT_EXIST")
        assert "error" in result["result"]

    def test_hallucination_guard_unknown_device(self, sandbox):
        """LLM must not be able to query invented devices."""
        result = sandbox.get_blast_radius("INVENTED_DEVICE_XYZ")
        assert "error" in result["result"]
        # Known devices should be listed in error to help the agent
        assert "R1" in result["result"]["error"] or "Known" in result["result"]["error"]


# ---------------------------------------------------------------------------
# Layer 3 — find_shortest_path
# ---------------------------------------------------------------------------


class TestFindShortestPath:
    def test_direct_link_r1_r2(self, sandbox):
        result = sandbox.find_shortest_path("R1", "R2")
        assert result["result"]["hop_count"] == 1
        assert result["result"]["path"] == ["R1", "R2"]

    def test_r1_to_r3_direct_link_exists(self, sandbox):
        result = sandbox.find_shortest_path("R1", "R3")
        # Direct link exists R1→R3 (hop 1), also via R2 (hop 2)
        assert result["result"]["hop_count"] == 1

    def test_path_contains_correct_nodes(self, sandbox):
        result = sandbox.find_shortest_path("R1", "R2")
        path = result["result"]["path"]
        assert path[0] == "R1"
        assert path[-1] == "R2"

    def test_hops_list_populated(self, sandbox):
        result = sandbox.find_shortest_path("R1", "R2")
        assert len(result["result"]["hops"]) >= 1

    def test_no_path_returns_error_result(self):
        """Disconnected graph should return explicit no_path."""
        snap = ControlPlaneSnapshot(
            devices=[Device(name="R1"), Device(name="R2")],
            topology_links=[],  # no edges
        )
        sb = OpsNetworkXSandbox(snap)
        result = sb.find_shortest_path("R1", "R2")
        assert result["result"]["path"] is None
        assert "error" in result["result"]

    def test_unknown_src_rejected(self, sandbox):
        result = sandbox.find_shortest_path("GHOST_SRC", "R2")
        assert "error" in result["result"]

    def test_unknown_dst_rejected(self, sandbox):
        result = sandbox.find_shortest_path("R1", "GHOST_DST")
        assert "error" in result["result"]

    def test_hallucination_guard_both_unknown(self, sandbox):
        result = sandbox.find_shortest_path("FAKE_A", "FAKE_B")
        assert "error" in result["result"]


# ---------------------------------------------------------------------------
# Layer 4 — test_hypothesis
# ---------------------------------------------------------------------------


class TestTestHypothesis:
    # --- device_down -------------------------------------------------------

    def test_device_down_r2_affects_r1_r3(self, sandbox):
        result = sandbox.test_hypothesis({"type": "device_down", "device": "R2"})
        neighbors = result["result"]["affected_neighbors"]
        assert "R1" in neighbors
        assert "R3" in neighbors

    def test_device_down_returns_remaining_node_count(self, sandbox):
        result = sandbox.test_hypothesis({"type": "device_down", "device": "R2"})
        # 3 devices − 1 = 2
        assert result["result"]["remaining_node_count"] == 2

    def test_device_down_live_graph_not_mutated(self, sandbox):
        """Core contract: live graph must remain unchanged after simulation."""
        original_nodes = sandbox.node_count
        original_edges = sandbox.edge_count
        sandbox.test_hypothesis({"type": "device_down", "device": "R2"})
        assert sandbox.node_count == original_nodes
        assert sandbox.edge_count == original_edges

    def test_device_down_unknown_device_error(self, sandbox):
        result = sandbox.test_hypothesis({"type": "device_down", "device": "FAKE_R99"})
        assert "error" in result["result"]

    def test_device_down_requires_clab_when_bgp_affected(self, sandbox):
        result = sandbox.test_hypothesis({"type": "device_down", "device": "R1"})
        # R1 has BGP sessions, so CLAB validation must be recommended
        assert result["requires_clab_validation"] is True

    # --- link_down ---------------------------------------------------------

    def test_link_down_r2_r3(self, sandbox):
        result = sandbox.test_hypothesis({"type": "link_down", "src": "R2", "dst": "R3"})
        assert result["result"]["edges_removed"] > 0

    def test_link_down_alternate_path_via_r1(self, sandbox):
        result = sandbox.test_hypothesis({"type": "link_down", "src": "R2", "dst": "R3"})
        # R2→R3 link removed, but R2→R1→R3 should still exist
        assert result["result"]["path_still_exists"] is True

    def test_link_down_no_alternate_isolated(self):
        """Single link graph: removing it isolates R2."""
        snap = ControlPlaneSnapshot(
            devices=[Device(name="R1"), Device(name="R2")],
            topology_links=[
                TopologyLink(source="R1", target="R2"),
                TopologyLink(source="R2", target="R1"),
            ],
        )
        sb = OpsNetworkXSandbox(snap)
        result = sb.test_hypothesis({"type": "link_down", "src": "R1", "dst": "R2"})
        assert result["result"]["path_still_exists"] is False
        assert result["requires_clab_validation"] is True

    def test_link_down_live_graph_not_mutated(self, sandbox):
        original_edges = sandbox.edge_count
        sandbox.test_hypothesis({"type": "link_down", "src": "R1", "dst": "R2"})
        assert sandbox.edge_count == original_edges

    def test_link_down_unknown_src_error(self, sandbox):
        result = sandbox.test_hypothesis({"type": "link_down", "src": "GHOST", "dst": "R2"})
        assert "error" in result["result"]

    # --- bgp_session_down --------------------------------------------------

    def test_bgp_session_down_established(self, sandbox):
        result = sandbox.test_hypothesis({
            "type": "bgp_session_down",
            "device": "R1",
            "peer_ip": "192.168.1.3",
        })
        lost = result["result"]["lost_session"]
        assert lost["prior_state"] == "Established"
        assert result["requires_clab_validation"] is True

    def test_bgp_session_down_remaining_count(self, sandbox):
        result = sandbox.test_hypothesis({
            "type": "bgp_session_down",
            "device": "R2",
            "peer_ip": "192.168.1.3",
        })
        # R2 has 1 BGP session total, so 0 remaining
        assert result["result"]["remaining_bgp_sessions_on_device"] == 0

    def test_bgp_session_not_found_error(self, sandbox):
        result = sandbox.test_hypothesis({
            "type": "bgp_session_down",
            "device": "R1",
            "peer_ip": "9.9.9.9",  # does not exist
        })
        assert "error" in result["result"]

    # --- unknown type ------------------------------------------------------

    def test_unknown_hypothesis_type_error(self, sandbox):
        result = sandbox.test_hypothesis({"type": "teleport_router"})
        assert "error" in result["result"]
        assert "supported_types" in result["result"]


# ---------------------------------------------------------------------------
# SandboxResult.to_dict contract
# ---------------------------------------------------------------------------


class TestSandboxResult:
    def test_all_operations_return_dict(self, sandbox):
        """All public API methods must return plain dicts (not SandboxResult objects)."""
        r1 = sandbox.get_blast_radius("R1")
        r2 = sandbox.find_shortest_path("R1", "R3")
        r3 = sandbox.test_hypothesis({"type": "device_down", "device": "R2"})
        for r in (r1, r2, r3):
            assert isinstance(r, dict)
            assert "operation" in r
            assert "result" in r
            assert "reasoning_mode" in r
            assert r["reasoning_mode"] == "graph_heuristic"

    def test_evidence_sources_present(self, sandbox):
        result = sandbox.get_blast_radius("R1")
        assert isinstance(result["evidence_sources"], list)
        assert len(result["evidence_sources"]) > 0


# ---------------------------------------------------------------------------
# devices property (hallucination guard verification)
# ---------------------------------------------------------------------------


class TestDevicesProperty:
    def test_devices_list_matches_snapshot(self, sandbox, snapshot):
        assert set(sandbox.devices) == {d.name for d in snapshot.devices}

    def test_node_count_matches_device_count(self, sandbox, snapshot):
        assert sandbox.node_count == len(snapshot.devices)


# ---------------------------------------------------------------------------
# OSPF cost — edge weight projection
# ---------------------------------------------------------------------------


class TestOSPFCost:
    def test_ospf_cost_in_adjacency_dict(self, sandbox):
        """OSPF adjacency dicts must carry the cost field."""
        adjs = sandbox._graph.nodes["R1"]["ospf_adjacencies"]
        r1_adj = next((a for a in adjs if a["interface"] == "Gi0/0"), None)
        assert r1_adj is not None
        assert r1_adj["cost"] == 10

    def test_ospf_cost_on_edge(self, sandbox):
        """Topology edge R1→R2 must have ospf_cost=10 after projection."""
        G = sandbox._graph
        # Find the R1→R2 edge with source_iface=Gi0/0
        cost_found = None
        for u, v, data in G.edges(data=True):
            if u == "R1" and v == "R2" and data.get("source_iface") == "Gi0/0":
                cost_found = data.get("ospf_cost")
                break
        assert cost_found == 10

    def test_ospf_cost_high_path_prefers_low_cost(self):
        """find_shortest_path with weight=ospf_cost prefers lower-cost path."""
        # R1 → R2 (cost=10) vs R1 → R3 → R2 (cost=5+5=10 but topology different)
        # Use asymmetric costs to verify weight logic
        snap = ControlPlaneSnapshot(
            devices=[Device(name="A"), Device(name="B"), Device(name="C")],
            topology_links=[
                TopologyLink(source="A", target="B", source_iface="Gi0"),
                TopologyLink(source="A", target="C", source_iface="Gi1"),
                TopologyLink(source="C", target="B", source_iface="Gi0"),
            ],
            ospf_neighbors=[
                # A→B direct: cost=100 (high)
                OSPFNeighbor(device="A", neighbor_id="B", neighbor_ip="10.0.0.2", interface="Gi0", state="Full", cost=100),
                # A→C: cost=1, C→B: cost=1 → total 2 (low)
                OSPFNeighbor(device="A", neighbor_id="C", neighbor_ip="10.0.0.3", interface="Gi1", state="Full", cost=1),
                OSPFNeighbor(device="C", neighbor_id="B", neighbor_ip="10.0.0.2", interface="Gi0", state="Full", cost=1),
            ],
        )
        sb = OpsNetworkXSandbox(snap)
        result = sb.find_shortest_path("A", "B", weight="ospf_cost")
        # Should prefer A→C→B (cost=2) over A→B (cost=100)
        assert result["result"]["path"] == ["A", "C", "B"]

    def test_ospf_cost_none_falls_back_to_hop_count(self):
        """When OSPF cost is missing on all edges, path uses hop count."""
        snap = ControlPlaneSnapshot(
            devices=[Device(name="A"), Device(name="B")],
            topology_links=[
                TopologyLink(source="A", target="B"),
                TopologyLink(source="B", target="A"),
            ],
            ospf_neighbors=[
                OSPFNeighbor(device="A", neighbor_id="B", neighbor_ip="10.0.0.2",
                             interface="Gi0", state="Full", cost=None),
            ],
        )
        sb = OpsNetworkXSandbox(snap)
        result = sb.find_shortest_path("A", "B", weight="ospf_cost")
        assert result["result"]["hop_count"] == 1


# ---------------------------------------------------------------------------
# STP/MSTP — port projection
# ---------------------------------------------------------------------------


class TestSTPProjection:
    def test_stp_ports_attached_to_node(self, sandbox):
        ports = sandbox._graph.nodes["R1"]["stp_ports"]
        assert len(ports) >= 2

    def test_stp_root_port_present(self, sandbox):
        ports = sandbox._graph.nodes["R1"]["stp_ports"]
        roles = [p["role"] for p in ports]
        assert "Root" in roles

    def test_stp_blocking_port_on_r2(self, sandbox):
        ports = sandbox._graph.nodes["R2"]["stp_ports"]
        blocking = [p for p in ports if p["state"] == "BLK"]
        assert len(blocking) == 1
        assert blocking[0]["role"] == "Altn"

    def test_stp_vlan_id_preserved(self, sandbox):
        ports = sandbox._graph.nodes["R1"]["stp_ports"]
        assert all(p["vlan_id"] == "1" for p in ports)

    def test_stp_cost_preserved(self, sandbox):
        ports = sandbox._graph.nodes["R1"]["stp_ports"]
        assert all(p["cost"] == 100 for p in ports)

    def test_stp_empty_for_device_without_data(self):
        snap = ControlPlaneSnapshot(
            devices=[Device(name="R1")],
            stp_ports=[],
        )
        G = GraphBuilder().build(snap)
        StateProjector().project(G, snap)
        assert G.nodes["R1"]["stp_ports"] == []


# ---------------------------------------------------------------------------
# IS-IS — adjacency projection
# ---------------------------------------------------------------------------


class TestISISProjection:
    def test_isis_adj_attached_to_node(self, sandbox):
        adjs = sandbox._graph.nodes["R1"]["isis_adjacencies"]
        assert len(adjs) == 1
        assert adjs[0]["system_id"] == "0000.0000.0002"

    def test_isis_adj_state(self, sandbox):
        adjs = sandbox._graph.nodes["R1"]["isis_adjacencies"]
        assert adjs[0]["state"] == "Up"

    def test_isis_level_preserved(self, sandbox):
        adjs = sandbox._graph.nodes["R1"]["isis_adjacencies"]
        assert adjs[0]["level"] == "L2"

    def test_isis_empty_for_device_without_data(self, sandbox):
        # R3 has no IS-IS adjacencies in the fixture
        adjs = sandbox._graph.nodes["R3"]["isis_adjacencies"]
        assert adjs == []


# ---------------------------------------------------------------------------
# EVPN / VXLAN / MPLS — overlay projection
# ---------------------------------------------------------------------------


class TestOverlayProjection:
    def test_evpn_instance_attached(self, sandbox):
        insts = sandbox._graph.nodes["R1"]["evpn_instances"]
        assert len(insts) == 1
        assert insts[0]["evi"] == "10"
        assert insts[0]["vni"] == "10010"
        assert insts[0]["type"] == "L2"

    def test_vxlan_tunnel_attached(self, sandbox):
        tunnels = sandbox._graph.nodes["R1"]["vxlan_tunnels"]
        assert len(tunnels) == 1
        assert tunnels[0]["vni"] == "10010"
        assert tunnels[0]["remote_vtep"] == "192.168.1.3"

    def test_mpls_ldp_peer_attached(self, sandbox):
        peers = sandbox._graph.nodes["R1"]["mpls_ldp_peers"]
        assert len(peers) == 1
        assert peers[0]["ldp_peer"] == "192.168.1.2"
        assert peers[0]["state"] == "Oper"

    def test_evpn_empty_for_r2(self, sandbox):
        # Only R1 has EVPN in the fixture
        assert sandbox._graph.nodes["R2"]["evpn_instances"] == []

    def test_overlay_node_attrs_present_for_all_real_devices(self, sandbox):
        for dev in sandbox.real_devices:
            node = sandbox._graph.nodes[dev]
            for attr in ("evpn_instances", "vxlan_tunnels", "mpls_ldp_peers"):
                assert attr in node, f"{dev} missing {attr}"

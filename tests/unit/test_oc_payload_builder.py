"""Tests for oc_payload_builder — snapshot_to_srl_config (§15)."""

import sys
from pathlib import Path
_LAB_SCRIPTS = Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "lab" / "scripts"
if str(_LAB_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LAB_SCRIPTS))

import pytest

from olav.core.control_plane_ir import (
    BGPNeighbor,
    ControlPlaneSnapshot,
    Device,
    OSPFNeighbor,
    Route,
    TopologyLink,
)
from oc_payload_builder import snapshot_to_srl_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _snapshot_two_nodes() -> ControlPlaneSnapshot:
    """spine (AS65001) ↔ leaf (AS65002), P2P 10.99.0.0/30, loopbacks 192.168.1.x/32."""
    return ControlPlaneSnapshot(
        devices=[
            Device(name="spine", mgmt_ip="192.168.1.1", platform="arista_ceos"),
            Device(name="leaf",  mgmt_ip="192.168.1.2", platform="arista_ceos"),
        ],
        bgp_neighbors=[
            BGPNeighbor(device="spine", peer_ip="10.99.0.2", peer_as="65002", state="Established"),
            BGPNeighbor(device="leaf",  peer_ip="10.99.0.1", peer_as="65001", state="Established"),
        ],
        topology_links=[
            TopologyLink(
                source="spine", target="leaf",
                source_iface="eth1", target_iface="eth1",
                protocol="lldp", link_type="L3",
            ),
        ],
        routes=[
            Route(device="spine", network="10.99.0.0/30", next_hop="0.0.0.0", protocol="connected", metric="0"),
            Route(device="leaf",  network="10.99.0.0/30", next_hop="0.0.0.0", protocol="connected", metric="0"),
            Route(device="spine", network="10.99.0.1/32", next_hop="0.0.0.0", protocol="connected", metric="0"),
            Route(device="leaf",  network="10.99.0.2/32", next_hop="0.0.0.0", protocol="connected", metric="0"),
            Route(device="spine", network="192.168.1.1/32", next_hop="0.0.0.0", protocol="connected", metric="0"),
            Route(device="leaf",  network="192.168.1.2/32", next_hop="0.0.0.0", protocol="connected", metric="0"),
        ],
    )


def _empty_snapshot() -> ControlPlaneSnapshot:
    return ControlPlaneSnapshot()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSnapshotToSrlConfig:
    def test_returns_string(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        assert isinstance(cfg, str)

    def test_empty_snapshot_returns_comment_only(self):
        cfg = snapshot_to_srl_config("spine", _empty_snapshot())
        content = [l for l in cfg.splitlines() if l.strip() and not l.startswith("#")]
        assert content == []

    def test_unknown_node_returns_comment_only(self):
        cfg = snapshot_to_srl_config("nonexistent", _snapshot_two_nodes())
        content = [l for l in cfg.splitlines() if l.strip() and not l.startswith("#")]
        assert content == []

    def test_all_non_comment_lines_start_with_set_slash(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        for line in cfg.splitlines():
            if line.strip() and not line.startswith("#"):
                assert line.startswith("set /"), f"Line missing 'set /': {line!r}"

    def test_interface_present(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        assert "set / interface ethernet-1/1" in cfg

    def test_interface_ip_address(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        assert "10.99.0.1/30" in cfg

    def test_bgp_neighbor_command(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        assert "set / network-instance default protocols bgp neighbor 10.99.0.2" in cfg

    def test_bgp_peer_group_defined(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        assert "set / network-instance default protocols bgp group ebgp-65002" in cfg

    def test_bgp_peer_as_on_group(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        # peer-as is set on the group, not directly on the neighbor
        assert "group ebgp-65002 peer-as 65002" in cfg

    def test_bgp_neighbor_has_peer_group(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        assert "neighbor 10.99.0.2 peer-group ebgp-65002" in cfg

    def test_bgp_admin_state_enable(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        assert "admin-state enable" in cfg

    def test_bgp_transport_local_address(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        assert "transport local-address 10.99.0.1" in cfg

    def test_bgp_router_id_uses_loopback(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        assert "router-id 192.168.1.1" in cfg

    def test_bgp_afi_safi_ipv4_unicast(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        assert "afi-safi ipv4-unicast admin-state enable" in cfg

    def test_network_instance_default(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        assert "network-instance default" in cfg

    def test_leaf_config_uses_leaf_data(self):
        cfg = snapshot_to_srl_config("leaf", _snapshot_two_nodes())
        assert "peer-as 65001" in cfg
        assert "10.99.0.1" in cfg  # leaf's BGP peer
        assert "transport local-address 10.99.0.2" in cfg

    def test_bgp_only_for_requested_node(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        # leaf's BGP peer (10.99.0.1 as a neighbor) must NOT appear in spine's config
        assert "neighbor 10.99.0.1" not in cfg

    def test_multiple_bgp_sessions(self):
        snap = ControlPlaneSnapshot(
            bgp_neighbors=[
                BGPNeighbor(device="r1", peer_ip="10.0.0.2", peer_as="65002", state="Established"),
                BGPNeighbor(device="r1", peer_ip="10.0.0.6", peer_as="65003", state="Established"),
            ],
            topology_links=[
                TopologyLink(source="r1", target="r2", source_iface="eth1", target_iface="eth1",
                             protocol="lldp", link_type="L3"),
                TopologyLink(source="r1", target="r3", source_iface="eth2", target_iface="eth1",
                             protocol="lldp", link_type="L3"),
            ],
            routes=[
                Route(device="r1", network="10.0.0.0/30", next_hop="0.0.0.0", protocol="connected", metric="0"),
                Route(device="r1", network="10.0.0.4/30", next_hop="0.0.0.0", protocol="connected", metric="0"),
            ],
        )
        cfg = snapshot_to_srl_config("r1", snap)
        assert "neighbor 10.0.0.2" in cfg
        assert "neighbor 10.0.0.6" in cfg

    def test_ospf_section_when_neighbors_present(self):
        snap = ControlPlaneSnapshot(
            ospf_neighbors=[
                OSPFNeighbor(device="spine", neighbor_id="10.99.0.2", neighbor_ip="10.99.0.2",
                             interface="eth1", state="FULL", cost="10"),
            ],
        )
        cfg = snapshot_to_srl_config("spine", snap)
        assert "ospf" in cfg.lower()

    def test_no_ospf_section_when_no_neighbors(self):
        cfg = snapshot_to_srl_config("spine", _snapshot_two_nodes())
        assert "ospf" not in cfg.lower()

"""TDD tests for clab_topology_render — Step 1 of Phase 6 digital twin pipeline."""

import sys
from pathlib import Path
_LAB_SCRIPTS = Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "lab" / "scripts"
if str(_LAB_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LAB_SCRIPTS))

import pytest

from clab_cab import LabLink, LabNode, LabTopologySpec
from clab_topology_render import map_iface_to_srl, render_clab_topology


# ---------------------------------------------------------------------------
# map_iface_to_srl
# ---------------------------------------------------------------------------


class TestMapIfaceToSrl:
    def test_eth1(self):
        assert map_iface_to_srl("eth1") == "ethernet-1/1"

    def test_eth2(self):
        assert map_iface_to_srl("eth2") == "ethernet-1/2"

    def test_e1(self):
        assert map_iface_to_srl("e1") == "ethernet-1/1"

    def test_ethernet1(self):
        assert map_iface_to_srl("Ethernet1") == "ethernet-1/1"

    def test_ethernet2(self):
        assert map_iface_to_srl("Ethernet2") == "ethernet-1/2"

    def test_et0(self):
        assert map_iface_to_srl("Et0") == "ethernet-1/1"

    def test_et1(self):
        assert map_iface_to_srl("Et1") == "ethernet-1/1"

    def test_gi0_1(self):
        # GigabitEthernet0/1 → ethernet-1/1 (last number)
        assert map_iface_to_srl("Gi0/1") == "ethernet-1/1"

    def test_gi0_2(self):
        assert map_iface_to_srl("Gi0/2") == "ethernet-1/2"

    def test_gigabitethernet0_1(self):
        assert map_iface_to_srl("GigabitEthernet0/1") == "ethernet-1/1"

    def test_juniper_et(self):
        # et-0/0/0 → ethernet-1/1 (last segment + 1)
        assert map_iface_to_srl("et-0/0/0") == "ethernet-1/1"

    def test_juniper_et_2(self):
        assert map_iface_to_srl("et-0/0/1") == "ethernet-1/2"

    def test_already_srl(self):
        # already ethernet-1/1 → pass through
        assert map_iface_to_srl("ethernet-1/1") == "ethernet-1/1"

    def test_already_srl_2(self):
        assert map_iface_to_srl("ethernet-1/3") == "ethernet-1/3"

    def test_fallback_returns_index(self):
        assert map_iface_to_srl("unknown-iface", fallback_index=2) == "ethernet-1/2"

    def test_fallback_default(self):
        assert map_iface_to_srl("unknown-iface") == "ethernet-1/1"


# ---------------------------------------------------------------------------
# render_clab_topology
# ---------------------------------------------------------------------------


def _two_node_spec() -> LabTopologySpec:
    return LabTopologySpec(
        nodes=[
            LabNode(name="spine", platform="arista_ceos"),
            LabNode(name="leaf", platform="cisco_iosxr"),
        ],
        links=[
            LabLink(source="spine", target="leaf", source_iface="eth1", target_iface="eth1"),
        ],
        blast_radius_devices=["spine", "leaf"],
    )


class TestRenderClabTopology:
    def test_lab_name_prefixed(self):
        topo = render_clab_topology(_two_node_spec(), lab_name="mylab")
        assert topo["name"] == "cab-mylab"

    def test_prefix_empty_string(self):
        """prefix must be empty string so exec API returns short node names (not clab-<lab>-<node>)."""
        topo = render_clab_topology(_two_node_spec(), lab_name="x")
        assert topo.get("prefix") == ""

    def test_defaults_kind_srl(self):
        topo = render_clab_topology(_two_node_spec(), lab_name="x")
        assert topo["topology"]["defaults"]["kind"] == "srl"

    def test_defaults_image(self):
        topo = render_clab_topology(_two_node_spec(), lab_name="x", srl_image="ghcr.io/nokia/srlinux:24.3.1")
        assert topo["topology"]["defaults"]["image"] == "ghcr.io/nokia/srlinux:24.3.1"

    def test_default_image_used_when_not_specified(self):
        topo = render_clab_topology(_two_node_spec(), lab_name="x")
        assert "srlinux" in topo["topology"]["defaults"]["image"]

    def test_two_nodes_present(self):
        topo = render_clab_topology(_two_node_spec(), lab_name="x")
        nodes = topo["topology"]["nodes"]
        assert "spine" in nodes
        assert "leaf" in nodes
        assert len(nodes) == 2

    def test_one_link_present(self):
        topo = render_clab_topology(_two_node_spec(), lab_name="x")
        links = topo["topology"]["links"]
        assert len(links) == 1

    def test_link_endpoints_srl_format(self):
        topo = render_clab_topology(_two_node_spec(), lab_name="x")
        endpoints = topo["topology"]["links"][0]["endpoints"]
        assert endpoints[0] == "spine:ethernet-1/1"
        assert endpoints[1] == "leaf:ethernet-1/1"

    def test_no_startup_config_when_no_config_dir(self):
        topo = render_clab_topology(_two_node_spec(), lab_name="x")
        for node_cfg in topo["topology"]["nodes"].values():
            assert "startup-config" not in (node_cfg or {})

    def test_startup_config_added_when_config_dir(self, tmp_path):
        topo = render_clab_topology(_two_node_spec(), lab_name="x", config_dir=tmp_path)
        nodes = topo["topology"]["nodes"]
        assert nodes["spine"]["startup-config"] == str(tmp_path / "spine.cfg")
        assert nodes["leaf"]["startup-config"] == str(tmp_path / "leaf.cfg")

    def test_empty_spec(self):
        spec = LabTopologySpec(nodes=[], links=[], blast_radius_devices=[])
        topo = render_clab_topology(spec, lab_name="empty")
        assert topo["name"] == "cab-empty"
        assert topo["topology"]["nodes"] == {}
        assert topo["topology"]["links"] == []

    def test_multi_link(self):
        spec = LabTopologySpec(
            nodes=[
                LabNode(name="r1"), LabNode(name="r2"), LabNode(name="r3"),
            ],
            links=[
                LabLink(source="r1", target="r2", source_iface="eth1", target_iface="eth1"),
                LabLink(source="r2", target="r3", source_iface="eth2", target_iface="eth1"),
            ],
            blast_radius_devices=["r1", "r2", "r3"],
        )
        topo = render_clab_topology(spec, lab_name="multi")
        assert len(topo["topology"]["links"]) == 2
        eps = [lk["endpoints"] for lk in topo["topology"]["links"]]
        assert ["r1:ethernet-1/1", "r2:ethernet-1/1"] in eps
        assert ["r2:ethernet-1/2", "r3:ethernet-1/1"] in eps

    def test_node_with_none_interfaces(self):
        spec = LabTopologySpec(
            nodes=[LabNode(name="r1"), LabNode(name="r2")],
            links=[LabLink(source="r1", target="r2", source_iface=None, target_iface=None)],
            blast_radius_devices=["r1", "r2"],
        )
        topo = render_clab_topology(spec, lab_name="nulliface")
        # None interfaces should fall back to ethernet-1/1
        eps = topo["topology"]["links"][0]["endpoints"]
        assert eps[0] == "r1:ethernet-1/1"
        assert eps[1] == "r2:ethernet-1/1"

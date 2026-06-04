"""Tests for sim's inspector @tools.

The tools wrap ``model.graph`` + ``model.facts`` (built by
``graph_view.py``).  We mock ``load_network_model`` to return a
fixture model so tests don't depend on demo7 DB.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


_TOOL_SEARCH_PATHS = [
    # After @tool→scripts migration: tools live in analyzer/scripts, netops/tools, netops/scripts
    Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "netops" / "analyzer" / "scripts",
    Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "netops" / "tools",
    Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "netops" / "scripts",
]


def _load_tool(name: str):
    """Load a tool .py by searching known post-migration locations."""
    tool_path = None
    for search_dir in _TOOL_SEARCH_PATHS:
        candidate = search_dir / f"{name}.py"
        if candidate.exists():
            tool_path = candidate
            break
    if tool_path is None:
        import pytest
        pytest.skip(f"Tool {name}.py not found in known locations (moved or removed)", allow_module_level=True)
    
    spec = importlib.util.spec_from_file_location(f"sim_tool_{name}", tool_path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[f"sim_tool_{name}"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


_DEVICES_M = _load_tool("inspect_devices")
_TOPO_M = _load_tool("inspect_topology")
_ROUTING_M = _load_tool("inspect_routing")
_BLAST_M = _load_tool("inspect_blast_radius")


def _fixture_model():
    """Mock model with a small known graph: R1-R3-R4-R2 chain."""
    import networkx as nx
    g = nx.DiGraph()
    g.add_node("R1", platform="juniper_junos", local_as=65000,
               loopback="1.1.1.1", role="border")
    g.add_node("R2", platform="cisco_ios", local_as=65001,
               loopback="2.2.2.2", role="border")
    g.add_node("R3", platform="cisco_ios", local_as=65000,
               loopback="3.3.3.3", role="core")
    g.add_node("R4", platform="cisco_ios", local_as=65001,
               loopback="4.4.4.4", role="core")
    g.add_edge("R1", "R3", layer="L2", source_interface="ge-0/0/2",
               destination_interface="Eth0/0", protocol="LLDP",
               link_status="up")
    g.add_edge("R3", "R1", layer="L2", source_interface="Eth0/0",
               destination_interface="ge-0/0/2", protocol="LLDP",
               link_status="up", ospf_state="Full/BDR")
    g.add_edge("R3", "R4", layer="L2", source_interface="Eth0/1",
               destination_interface="Eth0/2", protocol="CDP",
               link_status="up")
    g.add_edge("R4", "R3", layer="L2", source_interface="Eth0/2",
               destination_interface="Eth0/1", protocol="CDP",
               link_status="up")
    g.add_edge("R4", "R2", layer="L2", source_interface="Eth0/0",
               destination_interface="GigE2", protocol="CDP",
               link_status="up", bgp_session=True,
               bgp_session_state="Established", bgp_neighbor_as=65001,
               ospf_state="Full/DR")
    g.add_edge("R2", "R4", layer="L2", source_interface="GigE2",
               destination_interface="Eth0/0", protocol="CDP",
               link_status="up", bgp_session=True,
               bgp_session_state="Established", bgp_neighbor_as=65001,
               ospf_state="Full/DR")
    facts = {n: dict(g.nodes[n]) for n in g.nodes}
    model = MagicMock()
    model.graph = g
    model.facts = facts
    return model


# ── inspect_devices ────────────────────────────────────────────────


def test_inspect_devices_returns_facts():
    with patch(
        "olav_netops.sim.load_network_model", return_value=_fixture_model()
    ):
        r = _DEVICES_M.inspect_devices.invoke({"devices": ["R2", "R3"]})
    assert r["R2"]["local_as"] == 65001
    assert r["R3"]["loopback"] == "3.3.3.3"
    assert r["R3"]["role"] == "core"


def test_inspect_devices_drops_unknown():
    with patch(
        "olav_netops.sim.load_network_model", return_value=_fixture_model()
    ):
        r = _DEVICES_M.inspect_devices.invoke({"devices": ["R2", "ZZZ"]})
    assert "R2" in r
    assert "ZZZ" not in r


# ── inspect_topology ───────────────────────────────────────────────


def test_inspect_topology_one_hop():
    with patch(
        "olav_netops.sim.load_network_model", return_value=_fixture_model()
    ):
        r = _TOPO_M.inspect_topology.invoke({"devices": ["R3"]})
    neighbors = {n["neighbor"] for n in r["R3"]}
    assert neighbors == {"R1", "R4"}
    # Each entry has interface + status
    for entry in r["R3"]:
        assert "local_intf" in entry
        assert entry["link_status"] == "up"


def test_inspect_topology_two_hops_extends():
    with patch(
        "olav_netops.sim.load_network_model", return_value=_fixture_model()
    ):
        r = _TOPO_M.inspect_topology.invoke({"devices": ["R3"], "depth": 2})
    neighbors = {n["neighbor"] for n in r["R3"]}
    # 1-hop: R1, R4; 2-hop adds R2 (via R4)
    assert "R2" in neighbors


# ── inspect_routing ────────────────────────────────────────────────


def test_inspect_routing_bgp_only():
    with patch(
        "olav_netops.sim.load_network_model", return_value=_fixture_model()
    ):
        r = _ROUTING_M.inspect_routing.invoke({"devices": ["R2"], "protocol": "bgp"})
    assert len(r["R2"]["bgp"]) == 1
    assert r["R2"]["bgp"][0]["neighbor"] == "R4"
    assert r["R2"]["bgp"][0]["neighbor_as"] == 65001
    assert r["R2"]["bgp"][0]["state"] == "Established"
    assert r["R2"]["ospf"] == []  # filtered out


def test_inspect_routing_both_protocols():
    with patch(
        "olav_netops.sim.load_network_model", return_value=_fixture_model()
    ):
        r = _ROUTING_M.inspect_routing.invoke({"devices": ["R2", "R3"]})
    assert r["R2"]["bgp"][0]["state"] == "Established"
    assert r["R2"]["ospf"][0]["state"] == "Full/DR"
    assert r["R3"]["ospf"]  # R3 has OSPF state on R3->R1 edge


# ── inspect_blast_radius ───────────────────────────────────────────


def test_inspect_blast_radius_device_failure():
    """Removing R3 disconnects R1 from the rest."""
    with patch(
        "olav_netops.sim.load_network_model", return_value=_fixture_model()
    ):
        r = _BLAST_M.inspect_blast_radius.invoke({"remove_devices": ["R3"]})
    assert r["removed_devices"] == ["R3"]
    # R3 was the only path; R1 isolates from {R2, R4}
    components_set = [set(c) for c in r["components"]]
    assert {"R1"} in components_set
    assert {"R2", "R4"} in components_set


def test_inspect_blast_radius_link_failure():
    """Removing R3-R4 link splits the network at the L2 level."""
    with patch(
        "olav_netops.sim.load_network_model", return_value=_fixture_model()
    ):
        r = _BLAST_M.inspect_blast_radius.invoke({
            "remove_links": [["R3", "R4"]],
        })
    components_set = [set(c) for c in r["components"]]
    # R1+R3 stays connected, R2+R4 stays connected, but the two halves split
    assert any("R1" in c and "R3" in c and "R4" not in c for c in components_set)
    assert any("R2" in c and "R4" in c and "R3" not in c for c in components_set)


def test_inspect_blast_radius_reports_loss():
    """connectivity_loss summary shows component count delta."""
    with patch(
        "olav_netops.sim.load_network_model", return_value=_fixture_model()
    ):
        r = _BLAST_M.inspect_blast_radius.invoke({"remove_devices": ["R3"]})
    assert r["connectivity_loss"]["pre_components"] == 1
    assert r["connectivity_loss"]["post_components"] >= 2


# ── tool schemas exposed correctly ─────────────────────────────────


def test_all_tools_expose_pydantic_schemas():
    """LangChain @tool decorator should expose args_schema for each."""
    for module, tool_name, required in [
        (_DEVICES_M, "inspect_devices", {"devices"}),
        (_TOPO_M, "inspect_topology", {"devices"}),
        (_ROUTING_M, "inspect_routing", {"devices"}),
        (_BLAST_M, "inspect_blast_radius", set()),
    ]:
        tool_fn = getattr(module, tool_name)
        schema = tool_fn.args_schema.model_json_schema()
        assert "properties" in schema
        for r in required:
            assert r in schema.get("required", []), (
                f"{tool_name}: {r} should be required"
            )

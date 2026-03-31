"""Tests for oc_config_builder — OC JSON → SRL-importable JSON.

Tests cover:
    merge_oc_records_for_device   — OC record merging + _unmapped extraction
    build_srl_json_from_oc_tree   — structural OC→SRL conversion
    build_srl_config_json         — full pipeline (top-level entry point)
"""

from __future__ import annotations

import sys
from pathlib import Path
_LAB_SCRIPTS = Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "lab" / "scripts"
if str(_LAB_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LAB_SCRIPTS))

import pytest

from oc_config_builder import (
    build_srl_config_json,
    build_srl_json_from_oc_tree,
    merge_oc_records_for_device,
)


# ---------------------------------------------------------------------------
# merge_oc_records_for_device
# ---------------------------------------------------------------------------


def test_merge_extracts_unmapped_fields():
    records = [
        {
            "openconfig-interfaces": {"interfaces": {"interface": [{"name": "GE1"}]}},
            "_unmapped": {"vendor_field": "val"},
        }
    ]
    tree, vendor = merge_oc_records_for_device(records)
    assert "openconfig-interfaces" in tree
    assert vendor == [{"vendor_field": "val"}]


def test_merge_skips_empty_unmapped():
    records = [{"openconfig-interfaces": {"interfaces": {}}, "_unmapped": {}}]
    tree, vendor = merge_oc_records_for_device(records)
    assert vendor == []


def test_merge_multiple_records_combined():
    records = [
        {"openconfig-interfaces": {"interfaces": {"interface": [{"name": "GE1"}]}}},
        {"openconfig-interfaces": {"interfaces": {"interface": [{"name": "GE2"}]}}},
    ]
    tree, _ = merge_oc_records_for_device(records)
    iface_list = tree["openconfig-interfaces"]["interfaces"]["interface"]
    assert len(iface_list) == 2


def test_merge_empty_records_returns_empty():
    tree, vendor = merge_oc_records_for_device([])
    assert tree == {}
    assert vendor == []


# ---------------------------------------------------------------------------
# build_srl_json_from_oc_tree — structural transformation
# ---------------------------------------------------------------------------


def _iface_oc_tree(iface_name="GigabitEthernet1", admin_status="UP"):
    return {
        "openconfig-interfaces": {
            "interfaces": {
                "interface": [
                    {
                        "name": iface_name,
                        "config": {
                            "name": iface_name,
                            "admin-status": admin_status,
                        },
                    }
                ]
            }
        }
    }


def test_srl_json_interface_list_top_level():
    tree = _iface_oc_tree()
    srl = build_srl_json_from_oc_tree(tree, iface_map={})
    assert "interface" in srl
    assert isinstance(srl["interface"], list)


def test_srl_json_admin_status_up_mapped_to_enable():
    tree = _iface_oc_tree(admin_status="UP")
    srl = build_srl_json_from_oc_tree(tree, iface_map={})
    iface = srl["interface"][0]
    assert iface.get("admin-state") == "enable"
    assert "admin-status" not in iface


def test_srl_json_admin_status_down_mapped_to_disable():
    tree = _iface_oc_tree(admin_status="DOWN")
    srl = build_srl_json_from_oc_tree(tree, iface_map={})
    iface = srl["interface"][0]
    assert iface.get("admin-state") == "disable"


def test_srl_json_config_container_flattened():
    """config/ wrapper removed — children merged into parent."""
    tree = _iface_oc_tree()
    srl = build_srl_json_from_oc_tree(tree, iface_map={})
    iface = srl["interface"][0]
    assert "config" not in iface
    assert "name" in iface


def test_srl_json_state_container_dropped():
    tree = {
        "openconfig-interfaces": {
            "interfaces": {
                "interface": [
                    {
                        "name": "GE1",
                        "config": {"name": "GE1"},
                        "state": {"oper-status": "UP"},
                    }
                ]
            }
        }
    }
    srl = build_srl_json_from_oc_tree(tree, iface_map={})
    iface = srl["interface"][0]
    assert "state" not in iface
    assert "oper-status" not in iface


def test_srl_json_iface_map_substitution():
    tree = _iface_oc_tree(iface_name="GigabitEthernet1")
    srl = build_srl_json_from_oc_tree(
        tree, iface_map={"GigabitEthernet1": "ethernet-1/1"}
    )
    iface = srl["interface"][0]
    assert iface["name"] == "ethernet-1/1"


def test_srl_json_loopback_filtered_when_iface_map_set():
    tree = {
        "openconfig-interfaces": {
            "interfaces": {
                "interface": [
                    {"name": "Loopback0", "config": {"name": "Loopback0"}},
                    {"name": "GigabitEthernet1", "config": {"name": "GigabitEthernet1"}},
                ]
            }
        }
    }
    srl = build_srl_json_from_oc_tree(
        tree, iface_map={"GigabitEthernet1": "ethernet-1/1"}
    )
    names = [i["name"] for i in srl.get("interface", [])]
    assert "ethernet-1/1" in names
    assert "Loopback0" not in names


def test_srl_json_network_instance_unwrapped():
    tree = {
        "openconfig-network-instance": {
            "network-instances": {
                "network-instance": [
                    {"name": "default", "config": {"name": "default"}}
                ]
            }
        }
    }
    srl = build_srl_json_from_oc_tree(tree, iface_map={})
    assert "network-instance" in srl
    ni = srl["network-instance"][0]
    assert ni["name"] == "default"
    assert "config" not in ni


def test_srl_json_bgp_protocol_list_unwrapped():
    """OC: protocols.protocol[identifier=BGP].bgp → SRL: protocols.bgp"""
    tree = {
        "openconfig-network-instance": {
            "network-instances": {
                "network-instance": [
                    {
                        "name": "default",
                        "config": {"name": "default"},
                        "protocols": {
                            "protocol": [
                                {
                                    "identifier": "BGP",
                                    "name": "BGP",
                                    "bgp": {
                                        "global": {
                                            "config": {"as": 65001}
                                        }
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        }
    }
    srl = build_srl_json_from_oc_tree(tree, iface_map={})
    ni = srl["network-instance"][0]
    assert "protocols" in ni
    assert "bgp" in ni["protocols"]
    assert "protocol" not in ni["protocols"]


# ---------------------------------------------------------------------------
# build_srl_config_json — top-level entry point
# ---------------------------------------------------------------------------


def test_build_srl_config_json_empty_records():
    srl, vendor = build_srl_config_json("r1", [], iface_map={})
    assert srl == {}
    assert vendor == []


def test_build_srl_config_json_interface_config():
    """Full pipeline: OC records → SRL JSON with interface admin-state."""
    oc_records = [
        {
            "openconfig-interfaces": {
                "interfaces": {
                    "interface": [
                        {
                            "name": "GigabitEthernet1",
                            "config": {
                                "name": "GigabitEthernet1",
                                "admin-status": "UP",
                            },
                        }
                    ]
                }
            }
        }
    ]
    srl, vendor = build_srl_config_json(
        "r1", oc_records, iface_map={"GigabitEthernet1": "ethernet-1/1"}
    )
    assert vendor == []
    iface_list = srl.get("interface", [])
    assert len(iface_list) == 1
    iface = iface_list[0]
    assert iface["name"] == "ethernet-1/1"
    assert iface.get("admin-state") == "enable"


def test_build_srl_config_json_vendor_fields_separated():
    oc_records = [
        {
            "openconfig-interfaces": {
                "interfaces": {"interface": [{"name": "GE1", "config": {"name": "GE1"}}]}
            },
            "_unmapped": {"vendor_custom": "value"},
        }
    ]
    srl, vendor = build_srl_config_json("r1", oc_records, iface_map={})
    assert vendor == [{"vendor_custom": "value"}]
    assert "interface" in srl


def test_build_srl_config_json_bgp_as_in_result():
    """BGP global AS ends up in network-instance.protocols.bgp."""
    oc_records = [
        {
            "openconfig-network-instance": {
                "network-instances": {
                    "network-instance": [
                        {
                            "name": "default",
                            "config": {"name": "default"},
                            "protocols": {
                                "protocol": [
                                    {
                                        "identifier": "BGP",
                                        "name": "BGP",
                                        "bgp": {
                                            "global": {
                                                "config": {"as": 65001, "router-id": "10.0.0.1"}
                                            }
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        }
    ]
    srl, _ = build_srl_config_json("r1", oc_records, iface_map={})
    ni_list = srl.get("network-instance", [])
    assert ni_list
    protocols = ni_list[0].get("protocols", {})
    bgp = protocols.get("bgp", {})
    global_cfg = bgp.get("global", {})
    assert global_cfg.get("as") == 65001 or global_cfg.get("autonomous-system") == 65001 or bgp.get("as") == 65001

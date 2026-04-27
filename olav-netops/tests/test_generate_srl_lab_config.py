"""Unit tests for the R89 generate_srl_lab_config tool.

R89 contract: take (devices, change_intent) and return per-node SRL
CLI deterministically, replacing the LLM-driven prod→SRL translation
that produced YANG-rejected paths in the Chapter 4 → Chapter 5
in-vivo run on 2026-04-27.

Covers:
  * eBGP direct happy path (2 nodes, /30 link)
  * lab IP allocation from arbitrary subnets
  * lab node naming (lowercase per CLAB convention)
  * peer-group + neighbor cross-references
  * input validation (missing fields, wrong intent type)
  * subnet validation (rejects too-narrow prefixes)
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


_TOOL_PATH = (
    Path(__file__).resolve().parents[1]
    / ".olav" / "workspace" / "ops" / "lab" / "tools"
    / "generate_srl_lab_config.py"
)
_spec = importlib.util.spec_from_file_location("_gslc", _TOOL_PATH)
_gslc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gslc)


# --- happy path -------------------------------------------------------------


def _basic_call():
    """Common 2-node eBGP setup used across tests."""
    return _gslc.generate_srl_lab_config.invoke({
        "devices": [
            {"name": "R1", "loopback": "1.1.1.1/32", "asn": 65000},
            {"name": "R4", "loopback": "4.4.4.4/32", "asn": 65001},
        ],
        "change_intent": {
            "type": "ebgp_direct",
            "lab_subnet": "172.16.99.0/30",
        },
    })


def test_basic_returns_ok_status():
    data = json.loads(_basic_call())
    assert data["status"] == "ok"
    assert data["intent_type"] == "ebgp_direct"


def test_basic_yields_lowercase_lab_nodes():
    data = json.loads(_basic_call())
    assert set(data["configs"].keys()) == {"r1", "r4"}


def test_basic_22_lines_per_node():
    data = json.loads(_basic_call())
    for node, cfg in data["configs"].items():
        lines = [ln for ln in cfg.splitlines() if ln.strip()]
        assert len(lines) == 22, f"{node}: {len(lines)} lines (expected 22)"


def test_basic_r1_uses_first_host_in_subnet():
    data = json.loads(_basic_call())
    r1 = data["configs"]["r1"]
    assert "set / interface ethernet-1/1 subinterface 0 ipv4 address 172.16.99.1/30" in r1
    assert "set / network-instance default protocols bgp neighbor 172.16.99.2 peer-group ebgp-r4" in r1


def test_basic_r4_uses_second_host_in_subnet():
    data = json.loads(_basic_call())
    r4 = data["configs"]["r4"]
    assert "set / interface ethernet-1/1 subinterface 0 ipv4 address 172.16.99.2/30" in r4
    assert "set / network-instance default protocols bgp neighbor 172.16.99.1 peer-group ebgp-r1" in r4


def test_basic_loopbacks_correct():
    data = json.loads(_basic_call())
    assert "set / interface system0 subinterface 0 ipv4 address 1.1.1.1/32" in data["configs"]["r1"]
    assert "set / interface system0 subinterface 0 ipv4 address 4.4.4.4/32" in data["configs"]["r4"]


def test_basic_router_id_uses_loopback_host():
    data = json.loads(_basic_call())
    assert "set / network-instance default protocols bgp router-id 1.1.1.1" in data["configs"]["r1"]
    assert "set / network-instance default protocols bgp router-id 4.4.4.4" in data["configs"]["r4"]


def test_basic_local_as_correct_per_node():
    data = json.loads(_basic_call())
    assert "set / network-instance default protocols bgp autonomous-system 65000" in data["configs"]["r1"]
    assert "set / network-instance default protocols bgp autonomous-system 65001" in data["configs"]["r4"]


def test_basic_peer_as_cross_referenced():
    """r1 peer-as is r4's local-as and vice-versa."""
    data = json.loads(_basic_call())
    assert "set / network-instance default protocols bgp group ebgp-r4 peer-as 65001" in data["configs"]["r1"]
    assert "set / network-instance default protocols bgp group ebgp-r1 peer-as 65000" in data["configs"]["r4"]


def test_basic_includes_required_yang_paths():
    """The 4 YANG paths that LLM-translation kept missing in v1 must be present."""
    data = json.loads(_basic_call())
    for node, cfg in data["configs"].items():
        # Connectivity: subinterface 0 ipv4 address (NOT connectivity-endpoint)
        assert "subinterface 0 ipv4 address" in cfg
        # No 'group ... type external' (SRL infers from peer-as)
        assert "type external" not in cfg
        # peer-group (mandatory)
        assert "peer-group ebgp-" in cfg
        # afi-safi ipv4-unicast enabled at instance level (not per-neighbor)
        assert "afi-safi ipv4-unicast admin-state enable" in cfg
        # ebgp-default-policy
        assert "ebgp-default-policy import-reject-all false" in cfg


def test_basic_loopback_export_policy_present():
    """Without this, eBGP reaches Established but exchanges 0 routes."""
    data = json.loads(_basic_call())
    for node, cfg in data["configs"].items():
        assert "routing-policy prefix-set loopbacks" in cfg
        assert "routing-policy policy export-bgp" in cfg
        assert "default-action policy-result reject" in cfg


def test_loopback_without_mask_works():
    """Accept loopback as bare host (no /32)."""
    result = _gslc.generate_srl_lab_config.invoke({
        "devices": [
            {"name": "R1", "loopback": "1.1.1.1", "asn": 65000},
            {"name": "R4", "loopback": "4.4.4.4", "asn": 65001},
        ],
        "change_intent": {
            "type": "ebgp_direct",
            "lab_subnet": "172.16.99.0/30",
        },
    })
    data = json.loads(result)
    assert data["status"] == "ok"
    assert "set / interface system0 subinterface 0 ipv4 address 1.1.1.1/32" in data["configs"]["r1"]


def test_default_lab_subnet():
    """Omitting lab_subnet uses 172.16.99.0/30."""
    result = _gslc.generate_srl_lab_config.invoke({
        "devices": [
            {"name": "R1", "loopback": "1.1.1.1/32", "asn": 65000},
            {"name": "R4", "loopback": "4.4.4.4/32", "asn": 65001},
        ],
        "change_intent": {"type": "ebgp_direct"},
    })
    data = json.loads(result)
    assert data["status"] == "ok"
    assert "172.16.99.1/30" in data["configs"]["r1"]


def test_alternative_subnet_works():
    result = _gslc.generate_srl_lab_config.invoke({
        "devices": [
            {"name": "A", "loopback": "10.0.0.1/32", "asn": 65000},
            {"name": "B", "loopback": "10.0.0.2/32", "asn": 65001},
        ],
        "change_intent": {
            "type": "ebgp_direct",
            "lab_subnet": "10.99.0.0/30",
        },
    })
    data = json.loads(result)
    assert data["status"] == "ok"
    assert "10.99.0.1/30" in data["configs"]["a"]
    assert "10.99.0.2/30" in data["configs"]["b"]


# --- input validation -------------------------------------------------------


def test_empty_devices_errors():
    result = _gslc.generate_srl_lab_config.invoke({
        "devices": [],
        "change_intent": {"type": "ebgp_direct"},
    })
    data = json.loads(result)
    assert data["status"] == "error"
    assert "non-empty" in data["error"].lower()


def test_wrong_device_count_for_ebgp_errors():
    """ebgp_direct needs exactly 2 devices."""
    result = _gslc.generate_srl_lab_config.invoke({
        "devices": [{"name": "R1", "loopback": "1.1.1.1/32", "asn": 65000}],
        "change_intent": {"type": "ebgp_direct"},
    })
    data = json.loads(result)
    assert data["status"] == "error"
    assert "2 devices" in data["error"].lower()


def test_missing_loopback_errors():
    result = _gslc.generate_srl_lab_config.invoke({
        "devices": [
            {"name": "R1", "asn": 65000},
            {"name": "R4", "loopback": "4.4.4.4/32", "asn": 65001},
        ],
        "change_intent": {"type": "ebgp_direct"},
    })
    data = json.loads(result)
    assert data["status"] == "error"
    assert "loopback" in data["error"].lower()


def test_missing_asn_errors():
    result = _gslc.generate_srl_lab_config.invoke({
        "devices": [
            {"name": "R1", "loopback": "1.1.1.1/32"},
            {"name": "R4", "loopback": "4.4.4.4/32", "asn": 65001},
        ],
        "change_intent": {"type": "ebgp_direct"},
    })
    data = json.loads(result)
    assert data["status"] == "error"
    assert "asn" in data["error"].lower()


def test_unsupported_intent_type_errors():
    result = _gslc.generate_srl_lab_config.invoke({
        "devices": [
            {"name": "R1", "loopback": "1.1.1.1/32", "asn": 65000},
            {"name": "R4", "loopback": "4.4.4.4/32", "asn": 65001},
        ],
        "change_intent": {"type": "ibgp_route_reflector"},
    })
    data = json.loads(result)
    assert data["status"] == "error"
    assert "unsupported" in data["error"].lower()


def test_too_narrow_subnet_errors():
    """/31 has only 2 hosts but the function rejects /31+ as ambiguous."""
    result = _gslc.generate_srl_lab_config.invoke({
        "devices": [
            {"name": "R1", "loopback": "1.1.1.1/32", "asn": 65000},
            {"name": "R4", "loopback": "4.4.4.4/32", "asn": 65001},
        ],
        "change_intent": {
            "type": "ebgp_direct",
            "lab_subnet": "172.16.99.0/31",
        },
    })
    data = json.loads(result)
    assert data["status"] == "error"
    assert "prefix" in data["error"].lower() or "/30" in data["error"]


def test_invalid_change_intent_type_rejected_by_pydantic():
    """LangChain's pydantic input validation rejects non-dict
    change_intent before our code runs. Either layer is fine — the
    test just verifies it doesn't pass through silently.
    """
    import pydantic_core
    with pytest.raises((pydantic_core.ValidationError, ValueError, TypeError)):
        _gslc.generate_srl_lab_config.invoke({
            "devices": [
                {"name": "R1", "loopback": "1.1.1.1/32", "asn": 65000},
                {"name": "R4", "loopback": "4.4.4.4/32", "asn": 65001},
            ],
            "change_intent": "not a dict",
        })

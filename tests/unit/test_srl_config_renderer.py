"""Tests for srl_config_renderer.

Two rendering paths:
    Primary   — render_device_srl_config_via_llm (LLM, no Python translation logic)
    Fallback  — render_device_srl_config (deterministic table-driven, no LLM)

Tests cover:
    oc_leaf_to_srl_cli          — deterministic rule table lookup
    render_device_srl_config    — full deterministic path (state→config, olav filter, iface_map)
    render_device_srl_config_via_llm — LLM path with injected mock llm_fn
"""

from __future__ import annotations

import sys
from pathlib import Path
_LAB_SCRIPTS = Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "lab" / "scripts"
if str(_LAB_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LAB_SCRIPTS))

import pytest

from srl_config_renderer import (
    oc_leaf_to_srl_cli,
    render_device_srl_config,
    render_device_srl_config_via_llm,
)


# ---------------------------------------------------------------------------
# oc_leaf_to_srl_cli — deterministic rule table
# ---------------------------------------------------------------------------


def test_oc_leaf_to_srl_cli_interface_admin_status_up():
    cmd = oc_leaf_to_srl_cli(
        oc_path="interfaces/interface/config/admin-status",
        value="UP",
        context={"interface": "ethernet-1/1"},
        iface_map={},
    )
    assert cmd == "set / interface ethernet-1/1 admin-state enable"


def test_oc_leaf_to_srl_cli_interface_admin_status_down():
    cmd = oc_leaf_to_srl_cli(
        oc_path="interfaces/interface/config/admin-status",
        value="DOWN",
        context={"interface": "ethernet-1/2"},
        iface_map={},
    )
    assert cmd == "set / interface ethernet-1/2 admin-state disable"


def test_oc_leaf_to_srl_cli_interface_mtu():
    cmd = oc_leaf_to_srl_cli(
        oc_path="interfaces/interface/config/mtu",
        value=9000,
        context={"interface": "ethernet-1/1"},
        iface_map={},
    )
    assert cmd == "set / interface ethernet-1/1 mtu 9000"


def test_oc_leaf_to_srl_cli_interface_ip_address_cidr():
    cmd = oc_leaf_to_srl_cli(
        oc_path="interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/config/ip",
        value="10.0.0.1/30",
        context={"interface": "ethernet-1/1"},
        iface_map={},
    )
    assert cmd == "set / interface ethernet-1/1 subinterface 0 ipv4 address 10.0.0.1/30 primary"


def test_oc_leaf_to_srl_cli_interface_ip_without_prefix_returns_none():
    cmd = oc_leaf_to_srl_cli(
        oc_path="interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/config/ip",
        value="10.0.0.1",
        context={"interface": "ethernet-1/1"},
        iface_map={},
    )
    assert cmd is None


def test_oc_leaf_to_srl_cli_bgp_neighbor_peer_as():
    cmd = oc_leaf_to_srl_cli(
        oc_path="network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/config/peer-as",
        value=65002,
        context={"neighbor-address": "10.0.0.2"},
        iface_map={},
    )
    assert cmd == "set / network-instance default protocols bgp neighbor 10.0.0.2 peer-as 65002"


def test_oc_leaf_to_srl_cli_bgp_global_as():
    cmd = oc_leaf_to_srl_cli(
        oc_path="network-instances/network-instance/protocols/protocol/bgp/global/config/as",
        value=65001,
        context={},
        iface_map={},
    )
    assert cmd == "set / network-instance default protocols bgp autonomous-system 65001"


def test_oc_leaf_to_srl_cli_bgp_global_router_id():
    cmd = oc_leaf_to_srl_cli(
        oc_path="network-instances/network-instance/protocols/protocol/bgp/global/config/router-id",
        value="10.0.0.1",
        context={},
        iface_map={},
    )
    assert cmd == "set / network-instance default protocols bgp router-id 10.0.0.1"


def test_oc_leaf_to_srl_cli_returns_none_for_unknown_path():
    cmd = oc_leaf_to_srl_cli(
        oc_path="some/completely/unknown/oc/path",
        value="whatever",
        context={},
        iface_map={},
    )
    assert cmd is None


def test_oc_leaf_to_srl_cli_applies_iface_map():
    cmd = oc_leaf_to_srl_cli(
        oc_path="interfaces/interface/config/admin-status",
        value="UP",
        context={"interface": "GigabitEthernet0/1"},
        iface_map={"GigabitEthernet0/1": "ethernet-1/1"},
    )
    assert cmd == "set / interface ethernet-1/1 admin-state enable"


def test_oc_leaf_to_srl_cli_bgp_neighbor_enabled_true():
    cmd = oc_leaf_to_srl_cli(
        oc_path="network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/config/enabled",
        value=True,
        context={"neighbor-address": "10.0.0.2"},
        iface_map={},
    )
    assert cmd == "set / network-instance default protocols bgp neighbor 10.0.0.2 admin-state enable"


# ---------------------------------------------------------------------------
# render_device_srl_config — deterministic path
# ---------------------------------------------------------------------------


def _bgp_fields() -> list[dict]:
    return [
        {"openconfig_path": "interfaces/interface/config/admin-status",
         "value": "UP", "interface": "ethernet-1/1"},
        {"openconfig_path": "interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/config/ip",
         "value": "10.0.0.1/30", "interface": "ethernet-1/1"},
        {"openconfig_path": "network-instances/network-instance/protocols/protocol/bgp/global/config/as",
         "value": 65001},
        {"openconfig_path": "network-instances/network-instance/protocols/protocol/bgp/global/config/router-id",
         "value": "10.0.0.1"},
        {"openconfig_path": "network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/config/peer-as",
         "value": 65002, "neighbor-address": "10.0.0.2"},
        {"openconfig_path": "network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/config/enabled",
         "value": True, "neighbor-address": "10.0.0.2"},
    ]


def test_render_device_srl_config_bgp_node_contains_expected_commands():
    cfg = render_device_srl_config("r1", _bgp_fields(), iface_map={}, db_path=None)
    assert "set / interface ethernet-1/1 admin-state enable" in cfg
    assert "set / interface ethernet-1/1 subinterface 0 ipv4 address 10.0.0.1/30 primary" in cfg
    assert "set / network-instance default protocols bgp autonomous-system 65001" in cfg
    assert "set / network-instance default protocols bgp router-id 10.0.0.1" in cfg
    assert "set / network-instance default protocols bgp neighbor 10.0.0.2 peer-as 65002" in cfg
    assert "set / network-instance default protocols bgp neighbor 10.0.0.2 admin-state enable" in cfg


def test_render_device_srl_config_empty_fields_returns_comment():
    cfg = render_device_srl_config("r1", [], iface_map={}, db_path=None)
    assert cfg.strip() == "" or cfg.strip().startswith("#")


def test_render_device_srl_config_olav_paths_skipped():
    """olav: namespace paths are silently skipped."""
    fields = [
        {"openconfig_path": "olav:custom/path", "value": "skip-me"},
        {"openconfig_path": "interfaces/interface/config/admin-status",
         "value": "UP", "interface": "ethernet-1/1"},
    ]
    cfg = render_device_srl_config("r1", fields, iface_map={}, db_path=None)
    assert "olav:" not in cfg
    assert "ethernet-1/1 admin-state enable" in cfg


def test_render_device_srl_config_unknown_paths_skipped():
    """Paths not in the rule table are silently skipped."""
    fields = [
        {"openconfig_path": "some/unknown/path", "value": "x"},
        {"openconfig_path": "interfaces/interface/config/admin-status",
         "value": "UP", "interface": "ethernet-1/1"},
    ]
    cfg = render_device_srl_config("r1", fields, iface_map={}, db_path=None)
    lines = [l for l in cfg.splitlines() if l.strip().startswith("set /")]
    assert len(lines) == 1
    assert "ethernet-1/1 admin-state enable" in lines[0]


def test_render_device_srl_config_state_paths_converted():
    """state/ paths are auto-converted to config/ equivalents."""
    fields = [{"openconfig_path": "interfaces/interface/state/admin-status",
               "value": "UP", "interface": "ethernet-1/1"}]
    cfg = render_device_srl_config("r1", fields, iface_map={}, db_path=None)
    assert "set / interface ethernet-1/1 admin-state enable" in cfg


def test_render_device_srl_config_applies_iface_map():
    fields = [{"openconfig_path": "interfaces/interface/config/admin-status",
               "value": "UP", "interface": "eth1"}]
    cfg = render_device_srl_config("r1", fields, iface_map={"eth1": "ethernet-1/1"}, db_path=None)
    assert "set / interface ethernet-1/1 admin-state enable" in cfg
    assert "eth1" not in cfg


def test_render_device_srl_config_loopback_skipped():
    """Loopback interfaces are not physical SRL ports — skip them."""
    fields = [
        {"openconfig_path": "interfaces/interface/config/admin-status",
         "value": "UP", "interface": "Loopback0"},
        {"openconfig_path": "interfaces/interface/config/admin-status",
         "value": "UP", "interface": "ethernet-1/1"},
    ]
    cfg = render_device_srl_config("r1", fields, iface_map={}, db_path=None)
    assert "Loopback0" not in cfg
    assert "ethernet-1/1" in cfg


# ---------------------------------------------------------------------------
# render_device_srl_config_via_llm — LLM path
# ---------------------------------------------------------------------------


def _mock_llm_fn(expected_commands: list[str]):
    """Returns a mock llm_fn that always outputs the given commands."""
    response = "\n".join(expected_commands)
    return lambda prompt: response


def test_llm_path_returns_set_commands():
    expected = [
        "set / network-instance default protocols bgp autonomous-system 65001",
        "set / network-instance default protocols bgp neighbor 10.0.0.2 peer-as 65002",
    ]
    cfg = render_device_srl_config_via_llm(
        device="r1",
        oc_fields=[{"openconfig_path": "bgp/global/config/as", "value": 65001}],
        iface_map={},
        llm_fn=_mock_llm_fn(expected),
    )
    for cmd in expected:
        assert cmd in cfg


def test_llm_path_filters_non_set_lines():
    """LLM response may contain explanation text — only set/ lines are kept."""
    def noisy_llm(prompt):
        return "Here are the commands:\nset / network-instance default protocols bgp autonomous-system 65001\nDone."

    cfg = render_device_srl_config_via_llm(
        device="r1",
        oc_fields=[{"openconfig_path": "bgp/global/config/as", "value": 65001}],
        iface_map={},
        llm_fn=noisy_llm,
    )
    lines = [l for l in cfg.splitlines() if l.strip()]
    assert all(l.startswith("set /") for l in lines)
    assert "Here are" not in cfg


def test_llm_path_empty_fields_returns_comment():
    cfg = render_device_srl_config_via_llm(
        device="r1",
        oc_fields=[],
        iface_map={},
        llm_fn=lambda p: "",
    )
    assert cfg.startswith("#")


def test_llm_path_includes_iface_map_in_prompt():
    """iface_map must be present in the prompt so LLM can translate interface names."""
    captured = []

    def capturing_llm(prompt):
        captured.append(prompt)
        return "set / interface ethernet-1/1 admin-state enable"

    render_device_srl_config_via_llm(
        device="r1",
        oc_fields=[{"openconfig_path": "interfaces/interface/config/admin-status",
                    "value": "UP", "interface": "GigabitEthernet1"}],
        iface_map={"GigabitEthernet1": "ethernet-1/1"},
        llm_fn=capturing_llm,
    )
    assert captured, "llm_fn was not called"
    assert "GigabitEthernet1" in captured[0]
    assert "ethernet-1/1" in captured[0]


def test_llm_path_includes_oc_fields_in_prompt():
    """All OC field data must appear in the prompt for the LLM to work with."""
    captured = []

    def capturing_llm(prompt):
        captured.append(prompt)
        return "set / network-instance default protocols bgp autonomous-system 65001"

    render_device_srl_config_via_llm(
        device="r1",
        oc_fields=[{"openconfig_path": "bgp/global/config/as", "value": 65001}],
        iface_map={},
        llm_fn=capturing_llm,
    )
    assert "bgp/global/config/as" in captured[0]
    assert "65001" in captured[0]

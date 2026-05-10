"""Tests for ARCH-32 free-interface picker."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from olav.core.cab.intf_picker import pick_free_interfaces


def _mock_occupied(occupied_map):
    """Patch _occupied_interfaces to return a fixed map."""
    return patch(
        "olav.core.cab.intf_picker._occupied_interfaces",
        return_value=occupied_map,
    )


def test_picks_lowest_free_cisco_ios():
    """Cisco IOS: Gi0/1 and Gi0/2 occupied → Gi0/3 picked."""
    with _mock_occupied({
        "R1": {"GigabitEthernet0/1", "GigabitEthernet0/2"},
    }):
        out = pick_free_interfaces(["R1"], {"R1": "cisco_ios"})
    assert out == {"R1": "GigabitEthernet0/3"}


def test_picks_lowest_free_junos():
    """Junos: ge-0/0/0 and ge-0/0/1 occupied → ge-0/0/2 picked."""
    with _mock_occupied({
        "R1": {"ge-0/0/0", "ge-0/0/1"},
    }):
        out = pick_free_interfaces(["R1"], {"R1": "juniper_junos"})
    assert out == {"R1": "ge-0/0/2"}


def test_picks_arista_eos():
    with _mock_occupied({"R1": {"Ethernet1", "Ethernet3"}}):
        out = pick_free_interfaces(["R1"], {"R1": "arista_eos"})
    assert out == {"R1": "Ethernet2"}


def test_first_intf_when_nothing_occupied():
    """Device exists in topology but with no rows → pick Gi0/1."""
    with _mock_occupied({"R1": set()}):
        out = pick_free_interfaces(["R1"], {"R1": "cisco_ios"})
    assert out == {"R1": "GigabitEthernet0/1"}


def test_unknown_platform_returns_none():
    """Unknown platform → None for that device, not raise."""
    with _mock_occupied({"R1": {"foo"}}):
        out = pick_free_interfaces(["R1"], {"R1": "unsupported_os"})
    assert out == {"R1": None}


def test_db_unavailable_returns_none_per_device():
    """When _occupied_interfaces returns {} (DB error), every device
    gets None so caller can fall back."""
    with _mock_occupied({}):
        out = pick_free_interfaces(
            ["R1", "R2"], {"R1": "cisco_ios", "R2": "juniper_junos"}
        )
    assert out == {"R1": None, "R2": None}


def test_short_form_intf_names_match():
    """Real LLDP/CDP rows often have 'Gi0/1' shorthand — picker must
    treat that as the same as 'GigabitEthernet0/1' for occupancy
    detection, not skip past it and pick a colliding interface."""
    with _mock_occupied({"R1": {"Gi0/1", "Gi0/2"}}):
        out = pick_free_interfaces(["R1"], {"R1": "cisco_ios"})
    assert out == {"R1": "GigabitEthernet0/3"}


def test_two_devices_independent():
    """Each device's occupancy is independent — R1's Gi0/1 occupation
    doesn't affect R2's pick."""
    with _mock_occupied({
        "R1": {"GigabitEthernet0/1", "GigabitEthernet0/2"},
        "R2": set(),  # nothing occupied
    }):
        out = pick_free_interfaces(
            ["R1", "R2"], {"R1": "cisco_ios", "R2": "cisco_ios"}
        )
    assert out == {"R1": "GigabitEthernet0/3", "R2": "GigabitEthernet0/1"}


def test_no_devices_returns_empty():
    out = pick_free_interfaces([], {})
    assert out == {}


def test_render_tcf_uses_picker_when_db_has_topology(tmp_path, monkeypatch):
    """End-to-end: tcf_writer asks the picker, picker returns Gi0/3
    because Gi0/1 + Gi0/2 are reported as occupied. Rendered prod CLI
    must contain Gi0/3, not the legacy hardcoded Gi0/1."""
    from pathlib import Path as _P

    from olav.core.cab.tcf_writer import render_tcf_from_change_plan

    fake_facts = {
        "RX": {"platform": "cisco_ios", "loopback": "10.10.10.10", "local_as": 65010},
        "RY": {"platform": "cisco_ios", "loopback": "10.10.10.20", "local_as": 65020},
    }
    plan = """
## Change Summary
```yaml
change_id: picker-integration-01
title: picker integration test
intent_type: ebgp_direct
devices: [RX, RY]
```
"""
    # Isolate state file
    monkeypatch.setattr(_P, "home", lambda: tmp_path)

    fake_occupied = {
        "RX": {"GigabitEthernet0/1", "GigabitEthernet0/2"},
        "RY": {"GigabitEthernet0/1"},
    }
    with patch(
        "olav.core.cab.tcf_writer._db_facts", return_value=fake_facts
    ), patch(
        "olav.core.cab.intf_picker._occupied_interfaces",
        return_value=fake_occupied,
    ):
        r = render_tcf_from_change_plan(
            plan, output_dir=tmp_path, lab_subnet="172.16.99.0/30",
        )

    assert r["status"] == "ok"
    yaml_text = (tmp_path / "picker-integration-01" / "spec.tcf.yaml").read_text()
    # RX should pick Gi0/3 (Gi0/1 + Gi0/2 occupied), RY should pick Gi0/2
    assert "interface GigabitEthernet0/3" in yaml_text, (
        "picker did not surface free interface for RX into rendered CLI"
    )
    assert "interface GigabitEthernet0/2" in yaml_text, (
        "picker did not surface free interface for RY into rendered CLI"
    )

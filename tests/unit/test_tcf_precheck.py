"""Tests for ARCH-34 pre_check rendering + schema."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import yaml

from olav.core.cab.tcf_schema import (
    CabTcf,
    CliBlock,
    Device,
    Intent,
    PreCheck,
)


def test_precheck_schema_rejects_unknown_device():
    """FK violation: pre_check refers to a device not in devices[]."""
    import pytest

    with pytest.raises(ValueError, match="pre_check.*references unknown device"):
        CabTcf(
            change_id="x",
            title="t",
            created_by="t",
            created_at=datetime.now(UTC),
            intent=Intent(type="ebgp_direct", lab_subnet="192.0.2.0/30"),
            devices=[Device(name="R1", platform="cisco_ios")],
            pre_check=[
                PreCheck(
                    device="GHOST",  # not in devices[]
                    check_id="PR-GHOST-test",
                    description="dangling pre-check",
                    command="show version",
                    expected_pattern="Cisco",
                ),
            ],
        )


def test_precheck_must_match_default_true():
    """must_match defaults to True (positive substring match)."""
    pc = PreCheck(
        device="R1",
        check_id="PR-test",
        description="d",
        command="cmd",
        expected_pattern="p",
    )
    assert pc.must_match is True


def test_precheck_must_match_false_for_absence_check():
    """must_match=False supports 'pattern must be ABSENT' semantics
    (used for subnet-not-routed: 'via ' must NOT appear)."""
    pc = PreCheck(
        device="R1",
        check_id="PR-subnet-clear",
        description="d",
        command="show ip route 192.0.2.0/30",
        expected_pattern="via ",
        must_match=False,
    )
    assert pc.must_match is False


def test_render_emits_pre_check_for_ebgp_direct(tmp_path, monkeypatch):
    """End-to-end: render_tcf_from_change_plan emits pre_check rows
    in the spec.tcf.yaml — 2 rows per device (subnet-clear + intf-free)."""
    from olav.core.cab.tcf_writer import render_tcf_from_change_plan

    # Isolate state file (lab_subnet pool)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    fake_facts = {
        "RA": {"platform": "cisco_ios", "loopback": "10.10.10.1", "local_as": 65001},
        "RB": {"platform": "cisco_ios", "loopback": "10.10.10.2", "local_as": 65002},
    }
    plan = """
## Change Summary
```yaml
change_id: pre-check-test-01
title: pre_check render test
intent_type: ebgp_direct
devices: [RA, RB]
```
"""
    with patch(
        "olav.core.cab.tcf_writer._db_facts", return_value=fake_facts
    ), patch(
        "olav.core.cab.intf_picker._occupied_interfaces",
        return_value={"RA": set(), "RB": set()},
    ):
        r = render_tcf_from_change_plan(
            plan, output_dir=tmp_path, lab_subnet="192.0.2.0/30",
        )

    assert r["status"] == "ok"
    assert r.get("pre_check_count") == 4, (
        f"expected 4 pre_check rows (2 per device); got {r.get('pre_check_count')}"
    )

    spec = yaml.safe_load(Path(r["spec_path"]).read_text())
    pre = spec["pre_check"]
    assert len(pre) == 4

    # Each device has subnet-clear + intf-free
    ra_checks = [p for p in pre if p["device"] == "RA"]
    rb_checks = [p for p in pre if p["device"] == "RB"]
    assert len(ra_checks) == 2
    assert len(rb_checks) == 2

    check_ids = {p["check_id"] for p in pre}
    assert "PR-RA-subnet-clear" in check_ids
    assert "PR-RA-intf-free" in check_ids
    assert "PR-RB-subnet-clear" in check_ids
    assert "PR-RB-intf-free" in check_ids

    # subnet-clear must be 'absence' check (must_match=False)
    subnet_clear = next(p for p in pre if p["check_id"] == "PR-RA-subnet-clear")
    assert subnet_clear["must_match"] is False
    assert "192.0.2.0/30" in subnet_clear["command"]

    # intf-free for Cisco: pattern "unassigned" must be present (must_match=True)
    intf_free = next(p for p in pre if p["check_id"] == "PR-RA-intf-free")
    assert intf_free["must_match"] is True
    assert intf_free["expected_pattern"] == "unassigned"


def test_render_pre_check_junos_intf_uses_inet_absence(tmp_path, monkeypatch):
    """For Junos, intf-free check is 'inet must NOT appear in show
    interfaces terse output'."""
    from olav.core.cab.tcf_writer import render_tcf_from_change_plan

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    fake_facts = {
        "JX": {"platform": "juniper_junos", "loopback": "10.10.10.1", "local_as": 65001},
        "JY": {"platform": "juniper_junos", "loopback": "10.10.10.2", "local_as": 65002},
    }
    plan = """
## Change Summary
```yaml
change_id: pre-check-junos-01
title: junos pre-check test
intent_type: ebgp_direct
devices: [JX, JY]
```
"""
    with patch(
        "olav.core.cab.tcf_writer._db_facts", return_value=fake_facts
    ), patch(
        "olav.core.cab.intf_picker._occupied_interfaces",
        return_value={"JX": set(), "JY": set()},
    ):
        r = render_tcf_from_change_plan(
            plan, output_dir=tmp_path, lab_subnet="192.0.2.0/30",
        )

    spec = yaml.safe_load(Path(r["spec_path"]).read_text())
    intf_free = next(p for p in spec["pre_check"] if p["check_id"] == "PR-JX-intf-free")
    assert intf_free["expected_pattern"] == "inet"
    assert intf_free["must_match"] is False  # absence proves freeness on Junos
    assert "show interfaces" in intf_free["command"]
    assert "terse" in intf_free["command"]

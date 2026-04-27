"""TCF file I/O tests — load/emit round-trip, atomicity, error cases."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from olav.core.cab import (
    CabTcf,
    CliBlock,
    Device,
    Intent,
    PostCheck,
    TvtRow,
    tcf_emit,
    tcf_load,
)


def _sample_tcf() -> CabTcf:
    return CabTcf(
        change_id="cab_io_test",
        title="IO test",
        created_by="ops-analyze",
        created_at=datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC),
        risk_class="low",
        intent=Intent(type="ebgp_direct", lab_subnet="172.16.99.0/30"),
        devices=[
            Device(
                name="R1",
                platform="juniper_junos",
                prod_loopback="1.1.1.1",
                prod_asn=65000,
            ),
            Device(
                name="R4",
                platform="cisco_ios",
                prod_loopback="4.4.4.4",
                prod_asn=65001,
            ),
        ],
        implementation=[
            CliBlock(
                device="R1",
                phase=1,
                cli=[
                    "set protocols bgp group ebgp-r4 type external",
                    "set protocols bgp group ebgp-r4 neighbor 10.1.24.2 peer-as 65001",
                ],
            ),
        ],
        post_check=[
            PostCheck(
                device="R1",
                check_id="bgp_up",
                description="BGP up",
                command="show bgp summary",
                expected_pattern="Established",
            ),
        ],
        tvt=[
            TvtRow(
                test_id="T1",
                description="BGP up",
                expected="Established",
                severity="blocker",
            ),
        ],
        required_tests=["T1"],
    )


# --- emit + load round-trip -------------------------------------------------


def test_emit_creates_file(tmp_path):
    tcf = _sample_tcf()
    out = tcf_emit(tcf, tmp_path / "spec.tcf.yaml")
    assert out.exists()
    assert out.is_file()


def test_emit_load_round_trip_preserves_data(tmp_path):
    tcf = _sample_tcf()
    out = tcf_emit(tcf, tmp_path / "spec.tcf.yaml")
    loaded = tcf_load(out)

    assert loaded.change_id == tcf.change_id
    assert loaded.title == tcf.title
    assert loaded.intent.type == tcf.intent.type
    assert len(loaded.devices) == len(tcf.devices)
    assert loaded.devices[0].name == "R1"
    assert loaded.devices[0].prod_asn == 65000
    assert loaded.implementation[0].cli[0].startswith(
        "set protocols bgp group ebgp-r4 type external"
    )
    assert loaded.post_check[0].expected_pattern == "Established"
    assert loaded.tvt[0].test_id == "T1"


def test_emit_yaml_is_human_readable(tmp_path):
    """Output should look natural to a human reader — no flow-style
    inline garbage, keys in their declared order."""
    tcf = _sample_tcf()
    out = tcf_emit(tcf, tmp_path / "spec.tcf.yaml")
    text = out.read_text(encoding="utf-8")
    # Check declared key order shows up first
    assert text.index("schema_version:") < text.index("change_id:")
    assert text.index("change_id:") < text.index("title:")
    assert text.index("title:") < text.index("intent:")
    assert text.index("devices:") < text.index("implementation:")
    assert text.index("implementation:") < text.index("rollback:")
    assert text.index("tvt:") < text.index("lab:")
    assert text.index("lab:") < text.index("prod:")


def test_emit_creates_parent_dirs(tmp_path):
    tcf = _sample_tcf()
    nested = tmp_path / "deep" / "nested" / "dir" / "spec.tcf.yaml"
    out = tcf_emit(tcf, nested)
    assert out.exists()


def test_emit_overwrites_existing(tmp_path):
    """Re-emitting to the same path overwrites cleanly (atomic
    via os.replace)."""
    p = tmp_path / "spec.tcf.yaml"
    tcf1 = _sample_tcf()
    tcf_emit(tcf1, p)

    tcf2 = _sample_tcf()
    tcf2_dump = tcf2.model_copy(update={"title": "Updated title"})
    tcf_emit(tcf2_dump, p)

    loaded = tcf_load(p)
    assert loaded.title == "Updated title"


def test_emit_no_temp_file_left_on_success(tmp_path):
    tcf = _sample_tcf()
    p = tmp_path / "spec.tcf.yaml"
    tcf_emit(tcf, p)
    leftovers = [
        f for f in tmp_path.iterdir()
        if f.name.startswith(".") and f.name.endswith(".tmp")
    ]
    assert leftovers == [], f"leftover temp files: {leftovers}"


# --- error cases ------------------------------------------------------------


def test_load_missing_file_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        tcf_load(tmp_path / "does_not_exist.yaml")


def test_load_empty_file_raises(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    # ValidationError is what we want — we treat empty as "missing
    # required fields"
    with pytest.raises(ValidationError):
        tcf_load(p)


def test_load_non_mapping_yaml_raises(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        tcf_load(p)
    assert "mapping" in str(exc.value).lower()


def test_load_invalid_schema_raises_validation_error(tmp_path):
    """A YAML with valid syntax but bogus schema should raise."""
    p = tmp_path / "bad.yaml"
    bad = {
        "change_id": "x",
        "title": "y",
        "created_by": "z",
        "created_at": "2026-04-27T12:00:00",
        "intent": {"type": "ebgp"},
        "devices": [{"name": "R1", "platform": "p"}],
        "implementation": [{
            "device": "GHOST",  # FK violation
            "phase": 1,
            "cli": ["x"],
        }],
    }
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        tcf_load(p)
    assert "GHOST" in str(exc.value)


# --- emit rejects invalid TCF (Pydantic guard at construction) -----------


def test_pydantic_blocks_emit_of_invalid_tcf():
    """We can't even *build* a CabTcf with a FK violation — Pydantic
    validates at construction. So emit can never write garbage to
    disk."""
    with pytest.raises(ValidationError):
        CabTcf(
            change_id="x",
            title="y",
            created_by="z",
            created_at=datetime.now(UTC),
            intent=Intent(type="t"),
            devices=[Device(name="R1", platform="p")],
            implementation=[CliBlock(device="GHOST", phase=1, cli=["x"])],
        )


# --- YAML can be edited by hand and re-loaded --------------------------------


def test_hand_edited_yaml_loads(tmp_path):
    """Sanity: a hand-written minimal YAML loads correctly."""
    p = tmp_path / "hand.yaml"
    p.write_text(
        """
schema_version: 1
change_id: hand_test
title: Hand-edited TCF
created_by: human
created_at: 2026-04-27T12:00:00Z
risk_class: low
intent:
  type: vlan_add
  vlan_id: 100
devices:
  - name: SW1
    platform: arista_eos
    extras:
      ports: [Et1, Et2]
implementation:
  - device: SW1
    phase: 1
    cli:
      - "vlan 100"
      - "  name MyVLAN"
""",
        encoding="utf-8",
    )
    tcf = tcf_load(p)
    assert tcf.change_id == "hand_test"
    assert tcf.intent.type == "vlan_add"
    # Per-change-type intent extras flow through
    assert tcf.intent.model_dump().get("vlan_id") == 100
    # Per-device extras flow through
    assert tcf.devices[0].extras["ports"] == ["Et1", "Et2"]

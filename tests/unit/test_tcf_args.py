"""TCF arg-derivation helper tests — R88/R89/R90 args from a CabTcf."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from olav.core.cab import (
    CabTcf,
    CliBlock,
    Device,
    Intent,
    PostCheck,
    TvtRow,
    tcf_to_r88_args,
    tcf_to_r89_args,
    tcf_to_r90_args,
)


def _two_node_ebgp_tcf(
    *,
    intent_type: str = "ebgp_direct",
    lab_subnet: str | None = "172.16.99.0/30",
    drop_loopback_on: str | None = None,
    drop_asn_on: str | None = None,
    rollback: list[CliBlock] | None = None,
) -> CabTcf:
    intent_kwargs = {"type": intent_type}
    if lab_subnet:
        intent_kwargs["lab_subnet"] = lab_subnet

    devices = [
        Device(
            name="R1",
            platform="juniper_junos",
            prod_loopback=None if drop_loopback_on == "R1" else "1.1.1.1",
            prod_asn=None if drop_asn_on == "R1" else 65000,
        ),
        Device(
            name="R4",
            platform="cisco_ios",
            prod_loopback=None if drop_loopback_on == "R4" else "4.4.4.4",
            prod_asn=None if drop_asn_on == "R4" else 65001,
        ),
    ]

    return CabTcf(
        change_id="cab_args_test",
        title="Args test",
        created_by="ops-analyze",
        created_at=datetime.now(UTC),
        intent=Intent(**intent_kwargs),
        devices=devices,
        rollback=rollback or [],
    )


# --- tcf_to_r88_args --------------------------------------------------------


def test_r88_args_basic():
    tcf = _two_node_ebgp_tcf()
    args = tcf_to_r88_args(tcf)
    assert args["nodes"] == ["R1", "R4"]
    assert args["lab_name"] == "cab_args_test_lab"


def test_r88_args_lab_name_override():
    tcf = _two_node_ebgp_tcf()
    args = tcf_to_r88_args(tcf, lab_name="custom_lab")
    assert args["lab_name"] == "custom_lab"


def test_r88_args_empty_devices_errors():
    tcf = CabTcf(
        change_id="x",
        title="x",
        created_by="x",
        created_at=datetime.now(UTC),
        intent=Intent(type="t"),
        devices=[Device(name="X", platform="p")],
    )
    # Now wipe devices via direct assignment (Pydantic doesn't allow
    # via constructor since at least 1 needed). Test the helper's
    # explicit guard:
    tcf.devices = []
    with pytest.raises(ValueError) as exc:
        tcf_to_r88_args(tcf)
    assert "no devices" in str(exc.value).lower()


# --- tcf_to_r89_args --------------------------------------------------------


def test_r89_args_basic():
    tcf = _two_node_ebgp_tcf()
    args = tcf_to_r89_args(tcf)
    assert args == {
        "nodes": ["R1", "R4"],
        "loopbacks": ["1.1.1.1", "4.4.4.4"],
        "asns": [65000, 65001],
        "intent_type": "ebgp_direct",
        "lab_subnet": "172.16.99.0/30",
    }


def test_r89_args_omits_lab_subnet_when_not_in_intent():
    tcf = _two_node_ebgp_tcf(lab_subnet=None)
    args = tcf_to_r89_args(tcf)
    assert "lab_subnet" not in args
    assert args["intent_type"] == "ebgp_direct"


def test_r89_args_unknown_intent_type_errors():
    tcf = _two_node_ebgp_tcf(intent_type="vlan_add")
    with pytest.raises(ValueError) as exc:
        tcf_to_r89_args(tcf)
    msg = str(exc.value)
    assert "vlan_add" in msg
    assert "ebgp_direct" in msg  # mentions supported alternatives


def test_r89_args_missing_loopback_errors():
    tcf = _two_node_ebgp_tcf(drop_loopback_on="R4")
    with pytest.raises(ValueError) as exc:
        tcf_to_r89_args(tcf)
    assert "R4.prod_loopback" in str(exc.value)


def test_r89_args_missing_asn_errors():
    tcf = _two_node_ebgp_tcf(drop_asn_on="R1")
    with pytest.raises(ValueError) as exc:
        tcf_to_r89_args(tcf)
    assert "R1.prod_asn" in str(exc.value)


def test_r89_args_aggregates_multiple_missing_fields():
    """When several devices are short of fields, error names them
    all in one shot — not one-at-a-time."""
    tcf = _two_node_ebgp_tcf(drop_loopback_on="R1", drop_asn_on="R4")
    with pytest.raises(ValueError) as exc:
        tcf_to_r89_args(tcf)
    msg = str(exc.value)
    assert "R1.prod_loopback" in msg
    assert "R4.prod_asn" in msg


def test_r89_args_intent_extras_propagate():
    """When intent has change-type-specific fields beyond lab_subnet,
    they pass through (currently only lab_subnet is consumed by R89,
    but extra fields don't break the helper)."""
    tcf = CabTcf(
        change_id="cab_x",
        title="x",
        created_by="x",
        created_at=datetime.now(UTC),
        intent=Intent(
            type="ebgp_direct",
            lab_subnet="10.0.0.0/30",
            future_field="ignored_for_now",
        ),
        devices=[
            Device(name="R1", platform="x", prod_loopback="1.1.1.1", prod_asn=1),
            Device(name="R4", platform="x", prod_loopback="4.4.4.4", prod_asn=2),
        ],
    )
    args = tcf_to_r89_args(tcf)
    assert args["lab_subnet"] == "10.0.0.0/30"
    # future_field doesn't crash anything
    assert "future_field" not in args  # we don't pass through unknown intent fields


# --- tcf_to_r90_args --------------------------------------------------------


def test_r90_args_unknown_intent_errors():
    tcf = _two_node_ebgp_tcf(intent_type="vlan_add")
    with pytest.raises(ValueError) as exc:
        tcf_to_r90_args(tcf)
    assert "vlan_add" in str(exc.value)


def test_r90_args_missing_rollback_errors():
    tcf = _two_node_ebgp_tcf()  # rollback defaults to []
    with pytest.raises(ValueError) as exc:
        tcf_to_r90_args(tcf)
    assert "rollback list is empty" in str(exc.value).lower()


def test_r90_args_with_rollback_succeeds():
    rollback = [
        CliBlock(device="R1", phase="rb1", cli=["delete protocols bgp ..."]),
        CliBlock(device="R4", phase="rb1", cli=["no router bgp 65001"]),
    ]
    tcf = _two_node_ebgp_tcf(rollback=rollback)
    args = tcf_to_r90_args(tcf)
    # Same shape as R89 plus the rollback_blocks list
    assert args["nodes"] == ["R1", "R4"]
    assert args["loopbacks"] == ["1.1.1.1", "4.4.4.4"]
    assert args["asns"] == [65000, 65001]
    assert "rollback_blocks" in args
    assert len(args["rollback_blocks"]) == 2
    assert args["rollback_blocks"][0]["device"] == "R1"
    assert args["rollback_blocks"][0]["phase"] == "rb1"


def test_r90_args_inherits_r89_validation():
    """R90 builds on R89 args, so it inherits the loopback/asn
    requirement."""
    rollback = [CliBlock(device="R1", phase="rb1", cli=["delete x"])]
    tcf = _two_node_ebgp_tcf(rollback=rollback, drop_loopback_on="R1")
    with pytest.raises(ValueError) as exc:
        tcf_to_r90_args(tcf)
    assert "R1.prod_loopback" in str(exc.value)

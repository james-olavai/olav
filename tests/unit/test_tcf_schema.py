"""Pin the TCF (Test Case File) schema contract.

R90 Phase 1 tests covering:
  * happy path construction + serialisation
  * cross-FK validator (implementation/rollback/post_check → devices)
  * required_tests / optional_tests → tvt cross-reference
  * schema flexibility (extra fields, free-form intent.type / platform,
    open severity / status / risk_class strings)
  * default factories (lab/prod ExecutionRecords are PENDING)
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from olav.core.cab import (
    CabTcf,
    CliBlock,
    Device,
    ExecutionRecord,
    Intent,
    JournalEntry,
    PostCheck,
    TvtRow,
)
from olav.core.cab.tcf_schema import new_tcf


# --- happy path -------------------------------------------------------------


def _two_node_ebgp() -> CabTcf:
    """Common eBGP-direct fixture used across tests."""
    return CabTcf(
        change_id="cab_001",
        title="Add direct eBGP",
        created_by="ops-analyze",
        created_at=datetime.now(UTC),
        risk_class="low",
        intent=Intent(type="ebgp_direct", lab_subnet="172.16.99.0/30"),
        devices=[
            Device(
                name="R1",
                platform="juniper_junos",
                prod_intf="ge-0/0/2",
                prod_loopback="1.1.1.1",
                prod_asn=65000,
            ),
            Device(
                name="R4",
                platform="cisco_ios",
                prod_intf="Ethernet0/0",
                prod_loopback="4.4.4.4",
                prod_asn=65001,
            ),
        ],
        implementation=[
            CliBlock(device="R1", phase=1, cli=["set protocols bgp ..."]),
            CliBlock(device="R4", phase=1, cli=["router bgp 65001"]),
        ],
        rollback=[
            CliBlock(device="R1", phase="rb1", cli=["delete protocols bgp ..."]),
            CliBlock(device="R4", phase="rb1", cli=["no router bgp 65001"]),
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
                description="BGP r1↔r4 established",
                expected="Established",
                severity="blocker",
            ),
        ],
        required_tests=["T1"],
    )


def test_happy_path_constructs():
    tcf = _two_node_ebgp()
    assert tcf.schema_version == 1
    assert tcf.change_id == "cab_001"
    assert tcf.intent.type == "ebgp_direct"
    assert len(tcf.devices) == 2
    assert tcf.lab.verdict == "PENDING"  # default factory
    assert tcf.prod.verdict == "PENDING"


def test_new_tcf_helper():
    tcf = new_tcf(
        change_id="cab_test",
        title="test change",
        intent_type="ebgp_direct",
        lab_subnet="10.0.0.0/30",
        devices=[
            {"name": "X", "platform": "p"},
            {"name": "Y", "platform": "p"},
        ],
    )
    assert tcf.change_id == "cab_test"
    assert tcf.intent.type == "ebgp_direct"
    # extras flow through model_config["extra"] = "allow" — accessible via __pydantic_extra__
    assert tcf.intent.model_dump().get("lab_subnet") == "10.0.0.0/30"
    assert len(tcf.devices) == 2


# --- cross-FK validator -----------------------------------------------------


def test_implementation_dangling_device_rejected():
    base = _two_node_ebgp()
    bad = base.model_dump(mode="json")
    bad["implementation"].append({
        "device": "R99",  # NOT in devices
        "phase": 1,
        "cli": ["foo"],
    })
    with pytest.raises(ValidationError) as exc:
        CabTcf.model_validate(bad)
    assert "R99" in str(exc.value)


def test_rollback_dangling_device_rejected():
    base = _two_node_ebgp()
    bad = base.model_dump(mode="json")
    bad["rollback"].append({"device": "R42", "phase": "rb2", "cli": ["foo"]})
    with pytest.raises(ValidationError) as exc:
        CabTcf.model_validate(bad)
    assert "R42" in str(exc.value)


def test_post_check_dangling_device_rejected():
    base = _two_node_ebgp()
    bad = base.model_dump(mode="json")
    bad["post_check"].append({
        "device": "R7",
        "check_id": "x",
        "description": "y",
        "command": "z",
        "expected_pattern": "w",
    })
    with pytest.raises(ValidationError) as exc:
        CabTcf.model_validate(bad)
    assert "R7" in str(exc.value)


def test_required_tests_dangling_test_id_rejected():
    base = _two_node_ebgp()
    bad = base.model_dump(mode="json")
    bad["required_tests"] = ["T1", "T_DOES_NOT_EXIST"]
    with pytest.raises(ValidationError) as exc:
        CabTcf.model_validate(bad)
    assert "T_DOES_NOT_EXIST" in str(exc.value)


def test_optional_tests_dangling_test_id_rejected():
    base = _two_node_ebgp()
    bad = base.model_dump(mode="json")
    bad["optional_tests"] = ["T_GHOST"]
    with pytest.raises(ValidationError) as exc:
        CabTcf.model_validate(bad)
    assert "T_GHOST" in str(exc.value)


# --- schema flexibility (loose content, no Literal locks) -------------------


def test_intent_type_is_free_form():
    """Any string is acceptable as intent.type — new change types
    don't need a schema bump.
    """
    for t in [
        "ebgp_direct",
        "acl_update",
        "mtu_change",
        "vlan_add",
        "ospf_p2p",
        "static_route",
        "experimental_thingamajig",
    ]:
        intent = Intent(type=t)
        assert intent.type == t


def test_intent_extras_pass_through():
    """Per-change-type fields (lab_subnet, acl_name, ...) pass through
    model_config["extra"] = "allow"."""
    intent = Intent(type="acl_update", acl_name="BLOCK_RFC1918", direction="in")
    dumped = intent.model_dump()
    assert dumped["acl_name"] == "BLOCK_RFC1918"
    assert dumped["direction"] == "in"


def test_device_extras_pass_through():
    """Per-device extras (ospf_area, vlan_id, junos_version) carry
    through unchanged."""
    d = Device(
        name="R1",
        platform="juniper_junos",
        extras={"ospf_area": "0.0.0.0", "junos_version": "21.4"},
    )
    assert d.extras["ospf_area"] == "0.0.0.0"
    assert d.extras["junos_version"] == "21.4"


def test_device_top_level_extras_via_extra_allow():
    """``Device`` has extra='allow' — totally novel fields don't
    raise."""
    d = Device(name="R1", platform="x", brand_new_field="hello")
    assert d.model_dump().get("brand_new_field") == "hello"


def test_platform_is_free_form():
    """Any string platform — adding a new vendor doesn't need schema
    bump."""
    Device(name="X", platform="exotic_vendor")
    Device(name="Y", platform="acme_widget_os")  # accepted


def test_phase_int_or_str():
    """phase accepts ints (forward) and strings (rollback IDs)."""
    CliBlock(device="R1", phase=1, cli=["x"])
    CliBlock(device="R1", phase="rb1", cli=["y"])
    CliBlock(device="R1", phase="0-prereq", cli=["z"])


def test_severity_status_risk_class_open_strings():
    """severity / status / risk_class are open strings — different
    domains can use P0/P1/P2 or other vocabularies."""
    TvtRow(test_id="T", description="d", expected="e", severity="P0", status="WAIVED")
    # risk_class on top-level
    base = _two_node_ebgp()
    dumped = base.model_dump(mode="json")
    dumped["risk_class"] = "exotic-tier"
    CabTcf.model_validate(dumped)


# --- defaults / lifecycle ---------------------------------------------------


def test_lab_and_prod_default_to_pending():
    tcf = _two_node_ebgp()
    assert tcf.lab == ExecutionRecord()  # all defaults
    assert tcf.prod == ExecutionRecord()
    assert tcf.lab.verdict == "PENDING"
    assert tcf.lab.journal == []
    assert tcf.prod.verdict == "PENDING"


def test_lab_journal_records_step_args():
    """Lab fills journal with structured tool-call records."""
    j = JournalEntry(
        step="generate_srl_lab_config",
        args={"nodes": ["R1", "R4"], "asns": [65000, 65001]},
        result_summary={"intent_type": "ebgp_direct", "configs_emitted": 2},
        timestamp=datetime.now(UTC),
    )
    assert j.step == "generate_srl_lab_config"
    assert j.args["nodes"] == ["R1", "R4"]


def test_journal_entry_extras_allowed():
    """JournalEntry has extra='allow' — tools can record extra fields
    they care about without schema migration."""
    j = JournalEntry(
        step="x",
        custom_field="hello",
        retry_count=3,
    )
    dumped = j.model_dump()
    assert dumped["custom_field"] == "hello"
    assert dumped["retry_count"] == 3


def test_tvt_row_actuals_default_to_none():
    """Sim writes expected; lab/prod fill actual_lab/actual_prod
    later."""
    row = TvtRow(test_id="T", description="d", expected="e")
    assert row.actual_lab is None
    assert row.actual_prod is None
    assert row.status == "PENDING"


# --- required-field enforcement ---------------------------------------------


def test_device_requires_name_and_platform():
    with pytest.raises(ValidationError):
        Device(name="X")  # missing platform
    with pytest.raises(ValidationError):
        Device(platform="x")  # missing name


def test_tcf_requires_change_id_title_intent_devices():
    """All four are required fields with no default."""
    with pytest.raises(ValidationError):
        CabTcf(
            title="x",
            created_by="y",
            created_at=datetime.now(UTC),
            intent=Intent(type="t"),
            devices=[],
        )  # missing change_id


def test_intent_requires_type():
    with pytest.raises(ValidationError):
        Intent()  # missing type


def test_post_check_requires_all_fields():
    with pytest.raises(ValidationError):
        PostCheck(device="X", check_id="c")  # missing description/command/expected

"""Tests for olav.core.cab.tcf_sim.tcf_emit_from_sim.

Sim-side TCF construction helper (R91 Step 3 fold of the
``tcf_emit_from_sim`` MCP wrapper). Returns dict envelope; callers
in the sandbox don't need json.loads.
"""
from __future__ import annotations

import json

from olav.core.cab import tcf_emit_from_sim, tcf_load


def _basic_args(**overrides):
    base = dict(
        change_id="cab_sim_test",
        title="Sim-side fold test",
        intent_type="ebgp_direct",
        device_names=["R1", "R4"],
        device_platforms=["juniper_junos", "cisco_ios"],
        device_loopbacks=["1.1.1.1", "4.4.4.4"],
        device_asns=[65000, 65001],
        implementation_json=json.dumps([
            {"device": "R1", "phase": 1, "cli": ["set protocols bgp ..."]},
            {"device": "R4", "phase": 1, "cli": ["router bgp 65001 ..."]},
        ]),
        post_check_json=json.dumps([
            {"device": "R1", "check_id": "bgp_up",
             "description": "BGP up", "command": "show bgp summary",
             "expected_pattern": "Established"},
        ]),
        tvt_json=json.dumps([
            {"test_id": "T1", "description": "BGP up",
             "expected": "Established", "severity": "blocker"},
        ]),
        required_test_ids=["T1"],
    )
    base.update(overrides)
    return base


def test_emit_refuses_to_overwrite_spec_with_lab_state(tmp_path):
    """HITL guard: a spec with lab.verdict / findings / revision_count > 0
    must not be silently overwritten by a fresh emit_from_sim — that
    would discard human-in-the-loop accumulated state."""
    # 1. Write v0
    out0 = tcf_emit_from_sim(**_basic_args(output_dir=tmp_path))
    assert out0["status"] == "ok"

    # 2. Simulate accumulated state (operator + lab activity)
    from olav.core.cab import tcf_emit, tcf_load, ProdReviewFinding
    spec_path = tmp_path / "cab_sim_test" / "spec.tcf.yaml"
    tcf = tcf_load(spec_path)
    tcf.lab.verdict = "PASS"
    tcf.lab.prod_review_findings = [
        ProdReviewFinding(severity="warn", device="R1",
                          category="assumes_baseline",
                          description="manually accepted")
    ]
    tcf.revision_count = 4
    tcf_emit(tcf, spec_path)

    # 3. Re-emit v0-style → must refuse
    out_block = tcf_emit_from_sim(**_basic_args(output_dir=tmp_path))
    assert out_block["status"] == "error"
    assert "tcf_patch_block" in out_block["error"]
    assert out_block["existing_revision_count"] == 4
    assert out_block["existing_lab_verdict"] == "PASS"

    # 4. State preserved — file not clobbered
    reloaded = tcf_load(spec_path)
    assert reloaded.lab.verdict == "PASS"
    assert len(reloaded.lab.prod_review_findings) == 1
    assert reloaded.revision_count == 4


def test_emit_overwrite_existing_bypass_works(tmp_path):
    """``overwrite_existing=True`` is the explicit "start over" lever."""
    out0 = tcf_emit_from_sim(**_basic_args(output_dir=tmp_path))
    assert out0["status"] == "ok"
    # Add lab state
    from olav.core.cab import tcf_emit, tcf_load
    spec_path = tmp_path / "cab_sim_test" / "spec.tcf.yaml"
    tcf = tcf_load(spec_path)
    tcf.revision_count = 7
    tcf_emit(tcf, spec_path)

    # Bypass guard — should succeed
    out = tcf_emit_from_sim(
        **_basic_args(output_dir=tmp_path),
        overwrite_existing=True,
    )
    assert out["status"] == "ok"
    # Fresh state (revision_count back to 0)
    reloaded = tcf_load(spec_path)
    assert reloaded.revision_count == 0


def test_emit_writes_when_existing_spec_is_pristine(tmp_path):
    """Existing file with no accumulated state (verdict=PENDING,
    revision_count=0) is fine to overwrite — represents "the prior
    emit failed and we're trying again before lab even ran"."""
    out0 = tcf_emit_from_sim(**_basic_args(output_dir=tmp_path))
    assert out0["status"] == "ok"
    # Don't add any lab state — file is still pristine v0

    out = tcf_emit_from_sim(**_basic_args(output_dir=tmp_path,
                                          title="Updated title v0"))
    assert out["status"] == "ok"


def test_basic_emit_writes_tcf(tmp_path):
    out = tcf_emit_from_sim(**_basic_args(output_dir=tmp_path))
    assert out["status"] == "ok"
    assert out["device_count"] == 2
    assert out["implementation_blocks"] == 2
    assert out["tvt_count"] == 1
    spec_path = tmp_path / "cab_sim_test" / "spec.tcf.yaml"
    assert spec_path.exists()


def test_basic_emit_round_trips_through_load(tmp_path):
    tcf_emit_from_sim(**_basic_args(output_dir=tmp_path))
    loaded = tcf_load(tmp_path / "cab_sim_test" / "spec.tcf.yaml")
    assert loaded.change_id == "cab_sim_test"
    assert loaded.intent.type == "ebgp_direct"
    assert [d.name for d in loaded.devices] == ["R1", "R4"]
    assert loaded.devices[0].prod_asn == 65000
    assert loaded.required_tests == ["T1"]


def test_array_length_mismatch_errors(tmp_path):
    out = tcf_emit_from_sim(**_basic_args(
        output_dir=tmp_path,
        device_loopbacks=["1.1.1.1"],   # only 1 — mismatch
    ))
    assert out["status"] == "error"
    assert "device_*" in out["error"] or "length" in out["error"].lower()
    # No file written on error
    assert not (tmp_path / "cab_sim_test" / "spec.tcf.yaml").exists()


def test_invalid_json_string_errors(tmp_path):
    out = tcf_emit_from_sim(**_basic_args(
        output_dir=tmp_path,
        implementation_json="not-json",
    ))
    assert out["status"] == "error"
    assert "json" in out["error"].lower()


def test_intfs_optional_but_must_match_length_when_provided(tmp_path):
    out = tcf_emit_from_sim(**_basic_args(
        output_dir=tmp_path,
        device_intfs=["ge-0/0/2"],   # only 1 — should error (2 devices)
    ))
    assert out["status"] == "error"
    assert "intfs" in out["error"].lower()


def test_dangling_device_fk_in_implementation_errors(tmp_path):
    out = tcf_emit_from_sim(**_basic_args(
        output_dir=tmp_path,
        implementation_json=json.dumps([
            {"device": "R99", "phase": 1, "cli": ["..."]},  # not in devices
        ]),
    ))
    assert out["status"] == "error"
    # FK validator catches this when CabTcf is constructed
    assert "R99" in out["error"] or "construction" in out["error"].lower()


def test_intfs_provided_persisted_to_tcf(tmp_path):
    tcf_emit_from_sim(**_basic_args(
        output_dir=tmp_path,
        device_intfs=["ge-0/0/2", "Ethernet0/0"],
    ))
    loaded = tcf_load(tmp_path / "cab_sim_test" / "spec.tcf.yaml")
    assert loaded.devices[0].prod_intf == "ge-0/0/2"
    assert loaded.devices[1].prod_intf == "Ethernet0/0"

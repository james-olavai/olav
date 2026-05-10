"""Tests for ARCH-34 prod-side pre_check gate (run_prod_pre_check)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from olav.core.cab import (
    CabTcf,
    Device,
    Intent,
    make_dry_run_executor,
    run_prod_pre_check,
)
from olav.core.cab.tcf_schema import PreCheck


def _tcf_with_pre_check(rows: list[PreCheck]) -> CabTcf:
    return CabTcf(
        change_id="prod_gate_test",
        title="ARCH-34 prod gate test",
        created_by="sim",
        created_at=datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC),
        risk_class="low",
        intent=Intent(type="ebgp_direct", lab_subnet="192.0.2.0/30"),
        devices=[
            Device(name="R1", platform="cisco_ios",
                   prod_loopback="1.1.1.1", prod_asn=65000),
            Device(name="R2", platform="cisco_ios",
                   prod_loopback="2.2.2.2", prod_asn=65001),
        ],
        pre_check=rows,
    )


# --- GATE_PASS path --------------------------------------------------------


def test_all_checks_pass_returns_gate_pass():
    """Every pre_check satisfied → GATE_PASS, safe to push impl."""
    tcf = _tcf_with_pre_check([
        PreCheck(device="R1", check_id="PR-R1-subnet-clear",
                 description="d", command="show ip route 192.0.2.0/30",
                 expected_pattern="via ", must_match=False),
        PreCheck(device="R1", check_id="PR-R1-intf-free",
                 description="d", command="show ip int br Gi0/3",
                 expected_pattern="unassigned", must_match=True),
    ])
    executor = make_dry_run_executor({
        # Subnet not in routing table → no "via " in stdout → must_match=False satisfied
        ("R1", "show ip route 192.0.2.0/30"):
            {"stdout": "% Subnet not in table", "return_code": 0},
        # Interface unconfigured → contains "unassigned" → must_match=True satisfied
        ("R1", "show ip int br Gi0/3"):
            {"stdout": "Gi0/3   unassigned   YES   unset   admin down   down",
             "return_code": 0},
    })

    out = run_prod_pre_check(tcf, executor)

    assert out["verdict"] == "GATE_PASS"
    assert out["passed_count"] == 2
    assert out["failed_count"] == 0
    assert out["error_count"] == 0
    assert "Safe to push" in out["diagnosis"]


# --- GATE_FAIL path --------------------------------------------------------


def test_subnet_already_routed_returns_gate_fail():
    """must_match=False with pattern PRESENT → assertion fails → GATE_FAIL."""
    tcf = _tcf_with_pre_check([
        PreCheck(device="R1", check_id="PR-R1-subnet-clear",
                 description="lab subnet must not exist in routing table",
                 command="show ip route 192.0.2.0/30",
                 expected_pattern="via ", must_match=False),
    ])
    executor = make_dry_run_executor({
        # Subnet already routed → "via" present → must_match=False fails
        ("R1", "show ip route 192.0.2.0/30"):
            {"stdout": "S    192.0.2.0/30 [1/0] via 10.0.0.1\n",
             "return_code": 0},
    })

    out = run_prod_pre_check(tcf, executor)

    assert out["verdict"] == "GATE_FAIL"
    assert out["failed_count"] == 1
    assert out["passed_count"] == 0
    assert "ABORT implementation" in out["diagnosis"]
    assert "PR-R1-subnet-clear" in out["diagnosis"]


def test_interface_already_configured_returns_gate_fail():
    """must_match=True with pattern ABSENT → assertion fails → GATE_FAIL."""
    tcf = _tcf_with_pre_check([
        PreCheck(device="R1", check_id="PR-R1-intf-free",
                 description="interface must not have IP",
                 command="show ip int br Gi0/2",
                 expected_pattern="unassigned", must_match=True),
    ])
    executor = make_dry_run_executor({
        # Interface configured → no "unassigned" → must_match=True fails
        ("R1", "show ip int br Gi0/2"):
            {"stdout": "Gi0/2   10.99.0.1   YES   manual   up   up",
             "return_code": 0},
    })

    out = run_prod_pre_check(tcf, executor)

    assert out["verdict"] == "GATE_FAIL"
    assert out["failed_count"] == 1
    assert "PR-R1-intf-free" in out["diagnosis"]


def test_runs_all_checks_no_fail_fast():
    """Multiple failures all surface at once for HITL diagnosis."""
    tcf = _tcf_with_pre_check([
        PreCheck(device="R1", check_id="PR-R1-fail-A",
                 description="d", command="cmd-A",
                 expected_pattern="ALPHA", must_match=True),
        PreCheck(device="R1", check_id="PR-R1-fail-B",
                 description="d", command="cmd-B",
                 expected_pattern="BETA", must_match=True),
        PreCheck(device="R2", check_id="PR-R2-pass",
                 description="d", command="cmd-C",
                 expected_pattern="GAMMA", must_match=True),
    ])
    executor = make_dry_run_executor({
        ("R1", "cmd-A"): {"stdout": "nothing useful", "return_code": 0},
        ("R1", "cmd-B"): {"stdout": "nothing useful", "return_code": 0},
        ("R2", "cmd-C"): {"stdout": "GAMMA is here", "return_code": 0},
    })

    out = run_prod_pre_check(tcf, executor)

    assert out["verdict"] == "GATE_FAIL"
    assert out["failed_count"] == 2
    assert out["passed_count"] == 1
    # Both failures surface, not just the first
    assert "PR-R1-fail-A" in out["diagnosis"]
    assert "PR-R1-fail-B" in out["diagnosis"]


# --- GATE_ERROR path -------------------------------------------------------


def test_executor_raises_returns_gate_error():
    """Executor exception → GATE_ERROR, not GATE_FAIL."""
    tcf = _tcf_with_pre_check([
        PreCheck(device="R1", check_id="PR-R1-x",
                 description="d", command="cmd",
                 expected_pattern="x", must_match=True),
    ])

    def _bad_exec(device, command):
        raise ConnectionError("SSH timeout to R1")

    out = run_prod_pre_check(tcf, _bad_exec)

    assert out["verdict"] == "GATE_ERROR"
    assert out["error_count"] == 1
    assert out["passed_count"] == 0
    assert "transport" in out["diagnosis"]
    err_row = out["results"][0]
    assert err_row["exec_status"] == "error"
    assert "SSH timeout" in err_row["error"]


def test_executor_returns_error_dict_returns_gate_error():
    """Executor returns {error: ...} → GATE_ERROR."""
    tcf = _tcf_with_pre_check([
        PreCheck(device="R1", check_id="PR-R1-x",
                 description="d", command="cmd",
                 expected_pattern="x", must_match=True),
    ])
    # dry_run executor with no fixtures → returns {"error": ...}
    out = run_prod_pre_check(tcf, make_dry_run_executor({}))

    assert out["verdict"] == "GATE_ERROR"
    assert out["error_count"] == 1
    assert "no fixture" in out["results"][0]["error"]


def test_error_takes_precedence_over_fail():
    """If both errors AND fails present, verdict is GATE_ERROR.

    Connectivity failures need fixing before assertion failures
    can be trusted; reflect that in verdict ordering."""
    tcf = _tcf_with_pre_check([
        PreCheck(device="R1", check_id="PR-R1-fails",
                 description="d", command="cmd-fail",
                 expected_pattern="x", must_match=True),
        PreCheck(device="R2", check_id="PR-R2-errors",
                 description="d", command="cmd-err",
                 expected_pattern="y", must_match=True),
    ])

    def _exec(device, command):
        if device == "R2":
            raise TimeoutError("connection timeout")
        return {"stdout": "nothing useful", "return_code": 0}

    out = run_prod_pre_check(tcf, _exec)

    assert out["verdict"] == "GATE_ERROR"
    assert out["error_count"] == 1
    assert out["failed_count"] == 1


# --- NO_CHECKS path --------------------------------------------------------


def test_no_pre_check_rows_returns_no_checks():
    """Spec without pre_check rows → NO_CHECKS, caller decides."""
    tcf = _tcf_with_pre_check([])
    out = run_prod_pre_check(tcf, make_dry_run_executor({}))

    assert out["verdict"] == "NO_CHECKS"
    assert out["passed_count"] == 0
    assert out["failed_count"] == 0
    assert out["error_count"] == 0
    assert "no pre_check rows" in out["diagnosis"]


# --- Result row shape ------------------------------------------------------


def test_result_row_carries_full_provenance():
    """Each result row must carry enough info for HITL audit:
    check_id, device, command, expected_pattern, must_match, actual,
    passed, exec_status."""
    tcf = _tcf_with_pre_check([
        PreCheck(device="R1", check_id="PR-R1-x",
                 description="explicit description",
                 command="show foo",
                 expected_pattern="bar", must_match=True),
    ])
    executor = make_dry_run_executor({
        ("R1", "show foo"): {"stdout": "bar found", "return_code": 0},
    })
    out = run_prod_pre_check(tcf, executor)

    r = out["results"][0]
    assert r["check_id"] == "PR-R1-x"
    assert r["device"] == "R1"
    assert r["description"] == "explicit description"
    assert r["command"] == "show foo"
    assert r["expected_pattern"] == "bar"
    assert r["must_match"] is True
    assert r["exec_status"] == "ok"
    assert r["actual"] == "bar found"
    assert r["passed"] is True


def test_regex_pattern_with_re_prefix():
    """``re:<regex>`` prefix engages regex matching."""
    tcf = _tcf_with_pre_check([
        PreCheck(device="R1", check_id="PR-R1-x",
                 description="d", command="show ver",
                 expected_pattern=r"re:^Cisco IOS.*\s+Version\s+\d+\.\d+",
                 must_match=True),
    ])
    executor = make_dry_run_executor({
        ("R1", "show ver"): {
            "stdout": "Cisco IOS XE Software, Version 17.6",
            "return_code": 0,
        },
    })
    out = run_prod_pre_check(tcf, executor)

    assert out["verdict"] == "GATE_PASS"
    assert out["results"][0]["passed"] is True

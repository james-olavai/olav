"""Tests for olav.core.cab.tcf_validate.validate_tcf_in_lab.

Patch L atomic composite — wraps the 5+ step CAB lab validation
pipeline so the lab agent only makes ONE skill_script call.  Solves
ISSUE-CAB-AGENT-DRIVEN-LAB-VALIDATION-LOOPS (agent over-investigation
of intermediate steps).

Mocks at one seam: ``olav.platform.services.client.service_call``.
Everything else (TCF load, R88-A topology, R89 SRL, save_lab_config,
file-level deploy_and_push, tcf_record_lab_run) runs for real against
the tmp_path fixture.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from olav.core.cab import (
    CabTcf,
    CliBlock,
    Device,
    Intent,
    PostCheck,
    TvtRow,
    tcf_emit,
    tcf_load,
    validate_tcf_in_lab,
)
from olav.core.cab.tcf_schema import PreCheck


def _sample_tcf() -> CabTcf:
    return CabTcf(
        change_id="cab_validate_test",
        title="Patch L composite test",
        created_by="ops-analyze",
        created_at=datetime(2026, 5, 7, 12, 0, 0, tzinfo=UTC),
        risk_class="low",
        intent=Intent(type="ebgp_direct", lab_subnet="172.16.99.0/30"),
        devices=[
            Device(name="R1", platform="juniper_junos",
                   prod_loopback="1.1.1.1", prod_asn=65000),
            Device(name="R4", platform="cisco_ios",
                   prod_loopback="4.4.4.4", prod_asn=65001),
        ],
        implementation=[
            CliBlock(device="R1", phase=1,
                     cli=["set protocols bgp group ebgp-r4 peer-as 65001"]),
        ],
        post_check=[
            PostCheck(device="R1", check_id="bgp_up_r1",
                      description="BGP neighbor up on R1",
                      command="sr_cli 'show network-instance default protocols bgp neighbor'",
                      expected_pattern="established"),
            PostCheck(device="R4", check_id="bgp_up_r4",
                      description="BGP neighbor up on R4",
                      command="sr_cli 'show network-instance default protocols bgp neighbor'",
                      expected_pattern="established"),
        ],
        tvt=[
            TvtRow(test_id="bgp_up_r1", description="BGP up R1",
                   expected="Established", severity="blocker"),
            TvtRow(test_id="bgp_up_r4", description="BGP up R4",
                   expected="Established", severity="blocker"),
        ],
        required_tests=["bgp_up_r1", "bgp_up_r4"],
    )


def _mk_clab_exec_response(container_name: str, stdout: str) -> dict:
    """Mock CLAB /exec response shape: {container: [{stdout, ...}]}."""
    return {container_name: [{
        "stdout": stdout,
        "stderr": "",
        "return-code": 0,
    }]}


@pytest.fixture
def fake_service_call(monkeypatch):
    """Patch service_call in BOTH places it's imported.

    deploy_and_push_lab + destroy_lab + exec verification all import
    via ``from olav.platform.services.client import service_call``;
    patch the source module so all callers see the fake.
    """
    calls: list[dict] = []

    def _fake(service: str, *, method: str = "GET", path: str = "",
             params: dict | None = None, body: dict | None = None,
             confirmed: bool = False, timeout: float = 30.0):
        calls.append({
            "service": service, "method": method, "path": path,
            "params": params or {}, "body": body or {},
        })
        if service != "containerlab":
            raise AssertionError(f"unexpected service: {service}")

        # Deploy: POST /api/v1/labs
        if method == "POST" and path == "/api/v1/labs":
            return {"status": "deployed", "lab": body.get("name")}

        # Exec: POST /api/v1/labs/<lab_name>/exec
        if method == "POST" and "/exec" in path:
            container = (params or {}).get("nodeFilter", "unknown")
            # Default: BGP up — stdout contains "established"
            return _mk_clab_exec_response(
                container,
                "Net-Inst Peer            Group       AS    State\n"
                "default 172.16.99.2     ebgp-grp    65001 established",
            )

        # Destroy
        if method == "DELETE" and path.startswith("/api/v1/labs/"):
            return {"status": "destroyed"}

        # Lab-exists probe (GET) — pretend lab does NOT exist initially
        if method == "GET" and path.startswith("/api/v1/labs/"):
            raise RuntimeError("404 not found")

        return {}

    monkeypatch.setattr(
        "olav.platform.services.client.service_call",
        _fake,
    )
    return calls


# --- E2E PASS path ---------------------------------------------------------


def test_validate_tcf_in_lab_pass_path(tmp_path, fake_service_call):
    """All post-checks pass; verdict=PASS; TCF spec gets the lab section."""
    spec = tmp_path / "spec.tcf.yaml"
    tcf_emit(_sample_tcf(), spec)

    out = validate_tcf_in_lab(
        spec, deploy_wait_seconds=0,
        post_commit_wait_seconds=0, convergence_wait_seconds=0,
    )

    assert out["status"] == "ok", out
    assert out["verdict"] == "PASS"
    assert out["lab_name"] == "cab_validate_test_lab"
    assert out["spec_path"] == str(spec)
    assert len(out["post_check_results"]) == 2
    assert all(r["passed"] for r in out["post_check_results"])
    assert out["tcf_recorded"] is True
    assert out["lab_destroyed"] is True
    assert out["errors"] == []

    # Spec on disk now has the lab record
    reloaded = tcf_load(spec)
    assert reloaded.lab.verdict == "PASS"
    assert reloaded.lab.lab_name == "cab_validate_test_lab"
    assert len(reloaded.lab.journal) >= 4  # one per major phase


def test_validate_tcf_in_lab_fail_when_pattern_missing(
    tmp_path, monkeypatch
):
    """Post-check returns no 'established' → verdict=FAIL but pipeline
    still records and destroys."""
    spec = tmp_path / "spec.tcf.yaml"
    tcf_emit(_sample_tcf(), spec)

    def _fail_exec(service, *, method="GET", path="", params=None,
                   body=None, confirmed=False, timeout=30.0):
        if method == "POST" and path == "/api/v1/labs":
            return {"status": "deployed"}
        if method == "POST" and "/exec" in path:
            container = (params or {}).get("nodeFilter", "unknown")
            return _mk_clab_exec_response(container, "Peer  State: idle")
        if method == "DELETE":
            return {"status": "destroyed"}
        if method == "GET":
            raise RuntimeError("404 not found")
        return {}

    monkeypatch.setattr(
        "olav.platform.services.client.service_call", _fail_exec
    )

    out = validate_tcf_in_lab(
        spec, deploy_wait_seconds=0,
        post_commit_wait_seconds=0, convergence_wait_seconds=0,
    )

    assert out["status"] == "ok"
    assert out["verdict"] == "FAIL"
    assert all(not r["passed"] for r in out["post_check_results"])
    assert out["tcf_recorded"] is True
    assert out["lab_destroyed"] is True

    reloaded = tcf_load(spec)
    assert reloaded.lab.verdict == "FAIL"


# --- regex pattern handling -------------------------------------------------


def test_validate_tcf_in_lab_regex_pattern(tmp_path, monkeypatch):
    """expected_pattern with ``re:`` prefix uses regex matching."""
    tcf = _sample_tcf()
    tcf.post_check[0].expected_pattern = r"re:65001\s+established"
    tcf.post_check[1].expected_pattern = r"re:65000\s+established"
    spec = tmp_path / "spec.tcf.yaml"
    tcf_emit(tcf, spec)

    def _exec(service, *, method="GET", path="", params=None,
              body=None, confirmed=False, timeout=30.0):
        if method == "POST" and path == "/api/v1/labs":
            return {"status": "deployed"}
        if method == "POST" and "/exec" in path:
            container = (params or {}).get("nodeFilter", "unknown")
            # R1's neighbor is AS 65001; R4's neighbor is AS 65000
            asn = "65001" if "r1" in container else "65000"
            return _mk_clab_exec_response(
                container, f"172.16.99.x  ebgp-grp  {asn}  established"
            )
        if method == "DELETE":
            return {"status": "destroyed"}
        raise RuntimeError("404 not found")

    monkeypatch.setattr(
        "olav.platform.services.client.service_call", _exec
    )

    out = validate_tcf_in_lab(
        spec, deploy_wait_seconds=0,
        post_commit_wait_seconds=0, convergence_wait_seconds=0,
    )
    assert out["verdict"] == "PASS"
    assert all(r["passed"] for r in out["post_check_results"])


# --- error handling ---------------------------------------------------------


def test_validate_tcf_in_lab_missing_spec(tmp_path):
    out = validate_tcf_in_lab(tmp_path / "missing.yaml")
    assert out["status"] == "error"
    assert out["phase"] == "load"
    assert "not found" in out["error"].lower()


def test_validate_tcf_in_lab_skip_destroy(tmp_path, fake_service_call):
    """destroy_on_finish=False leaves the lab running."""
    spec = tmp_path / "spec.tcf.yaml"
    tcf_emit(_sample_tcf(), spec)

    out = validate_tcf_in_lab(
        spec, destroy_on_finish=False,
        deploy_wait_seconds=0, post_commit_wait_seconds=0,
        convergence_wait_seconds=0,
    )

    assert out["verdict"] == "PASS"
    assert out["lab_destroyed"] is False
    # Confirm no DELETE was issued
    deletes = [c for c in fake_service_call if c["method"] == "DELETE"]
    assert deletes == []


def test_validate_tcf_in_lab_skip_record(tmp_path, fake_service_call):
    """skip_record=True: don't write back to spec."""
    spec = tmp_path / "spec.tcf.yaml"
    tcf_emit(_sample_tcf(), spec)

    out = validate_tcf_in_lab(
        spec, skip_record=True,
        deploy_wait_seconds=0, post_commit_wait_seconds=0,
        convergence_wait_seconds=0,
    )

    assert out["verdict"] == "PASS"
    assert out["tcf_recorded"] is False
    reloaded = tcf_load(spec)
    # lab section was not touched — default verdict is "PENDING"
    assert reloaded.lab.verdict == "PENDING"
    assert reloaded.lab.lab_name is None


def test_validate_tcf_in_lab_forgiving_regex_when_bare_pattern(
    tmp_path, monkeypatch
):
    """Patch M tail-fix: bare expected_pattern with regex metacharacters
    (.* / \\s / \\d) — common sim emission style — should match as
    regex even without the ``re:`` prefix."""
    tcf = _sample_tcf()
    # Pattern uses .* but no re: prefix (real-world analyzer style)
    tcf.post_check[0].expected_pattern = "172.16.99.2.*65001.*established"
    tcf.post_check[1].expected_pattern = "172.16.99.1.*65000.*established"
    spec = tmp_path / "spec.tcf.yaml"
    tcf_emit(tcf, spec)

    def _exec(service, *, method="GET", path="", params=None,
              body=None, confirmed=False, timeout=30.0):
        if method == "POST" and path == "/api/v1/labs":
            return {"status": "deployed"}
        if method == "POST" and "/exec" in path:
            container = (params or {}).get("nodeFilter", "unknown")
            asn = "65001" if "r1" in container else "65000"
            peer = "172.16.99.2" if "r1" in container else "172.16.99.1"
            return {container: [{
                "stdout": (
                    "BGP neighbor summary\n"
                    f"| default | {peer} | ebgp-grp | S | {asn} | "
                    f"established | 0d:0h | ipv4 |"
                ),
                "stderr": "", "return-code": 0,
            }]}
        if method == "DELETE":
            return {"status": "destroyed"}
        raise RuntimeError("404 not found")

    monkeypatch.setattr(
        "olav.platform.services.client.service_call", _exec
    )

    out = validate_tcf_in_lab(
        spec, deploy_wait_seconds=0, post_commit_wait_seconds=0,
        convergence_wait_seconds=0,
    )
    assert out["verdict"] == "PASS"
    assert all(r["passed"] for r in out["post_check_results"])


def test_validate_tcf_in_lab_tvt_link_by_device_description(
    tmp_path, fake_service_call
):
    """Patch N tier 2: tvt rows mention device name in description;
    composite matches each tvt row to the post_check on that device."""
    tcf = _sample_tcf()
    # Make tvt IDs unrelated to check IDs (TC-* vs bgp_up_*)
    tcf.tvt[0].test_id = "TC-01"
    tcf.tvt[0].description = "BGP up R1"
    tcf.tvt[1].test_id = "TC-02"
    tcf.tvt[1].description = "BGP up R4"
    tcf.required_tests = ["TC-01", "TC-02"]
    spec = tmp_path / "spec.tcf.yaml"
    tcf_emit(tcf, spec)

    out = validate_tcf_in_lab(
        spec, deploy_wait_seconds=0, post_commit_wait_seconds=0,
        convergence_wait_seconds=0,
    )

    assert out["verdict"] == "PASS"
    # tvt_results should now have the TC-* rows linked by device match
    test_ids = {t["test_id"] for t in out["tvt_results"]}
    assert "TC-01" in test_ids
    assert "TC-02" in test_ids
    # Strategy recorded in journal
    journal_strategies = [
        e["result_summary"].get("strategy") for e in out["journal"]
        if e["step"] == "tvt_link"
    ]
    assert journal_strategies == ["by_device_in_description"]


def test_validate_tcf_in_lab_tvt_link_by_index(
    tmp_path, fake_service_call
):
    """Patch N tier 3: when nothing else matches, zip by index across
    required_tests + post_check (must have same length)."""
    tcf = _sample_tcf()
    # Ensure no exact match AND no device-name overlap with descriptions
    tcf.tvt[0].test_id = "TC-A"
    tcf.tvt[0].description = "First test"
    tcf.tvt[1].test_id = "TC-B"
    tcf.tvt[1].description = "Second test"
    tcf.required_tests = ["TC-A", "TC-B"]
    spec = tmp_path / "spec.tcf.yaml"
    tcf_emit(tcf, spec)

    out = validate_tcf_in_lab(
        spec, deploy_wait_seconds=0, post_commit_wait_seconds=0,
        convergence_wait_seconds=0,
    )

    assert out["verdict"] == "PASS"
    test_ids = [t["test_id"] for t in out["tvt_results"]]
    assert test_ids == ["TC-A", "TC-B"]
    journal_strategies = [
        e["result_summary"].get("strategy") for e in out["journal"]
        if e["step"] == "tvt_link"
    ]
    assert journal_strategies == ["by_index"]


def test_validate_tcf_in_lab_tvt_link_explicit_evidence(
    tmp_path, fake_service_call
):
    """Patch N tier 1: TvtRow has evidence_check_ids; composite uses
    them directly, ignoring fallbacks."""
    tcf = _sample_tcf()
    # Use the schema field directly (Patch N tier 1)
    tcf.tvt[0].test_id = "TC-A"
    tcf.tvt[0].description = "unrelated"
    tcf.tvt[0].evidence_check_ids = ["bgp_up_r1"]
    tcf.tvt[1].test_id = "TC-B"
    tcf.tvt[1].description = "also unrelated"
    tcf.tvt[1].evidence_check_ids = ["bgp_up_r4"]
    tcf.required_tests = ["TC-A", "TC-B"]
    spec = tmp_path / "spec.tcf.yaml"
    tcf_emit(tcf, spec)

    out = validate_tcf_in_lab(
        spec, deploy_wait_seconds=0, post_commit_wait_seconds=0,
        convergence_wait_seconds=0,
    )

    test_ids = sorted(t["test_id"] for t in out["tvt_results"])
    assert test_ids == ["TC-A", "TC-B"]
    # Provenance: which check produced each row
    from_checks = sorted(t["from_check_id"] for t in out["tvt_results"])
    assert from_checks == ["bgp_up_r1", "bgp_up_r4"]


def test_validate_tcf_in_lab_destroys_even_on_deploy_fail(
    tmp_path, monkeypatch
):
    """Deploy raises → still attempt destroy + return error envelope."""
    spec = tmp_path / "spec.tcf.yaml"
    tcf_emit(_sample_tcf(), spec)

    delete_called = []

    def _exec(service, *, method="GET", path="", params=None,
              body=None, confirmed=False, timeout=30.0):
        if method == "POST" and path == "/api/v1/labs":
            raise RuntimeError("simulated CLAB deploy failure")
        if method == "DELETE":
            delete_called.append(path)
            return {"status": "destroyed"}
        if method == "GET":
            raise RuntimeError("404 not found")
        return {}

    monkeypatch.setattr(
        "olav.platform.services.client.service_call", _exec
    )

    out = validate_tcf_in_lab(
        spec, deploy_wait_seconds=0,
        post_commit_wait_seconds=0, convergence_wait_seconds=0,
    )

    assert out["status"] == "error"
    assert out["phase"] == "deploy"
    assert out["lab_destroyed"] is True  # still attempted destroy
    assert delete_called  # DELETE was issued


# --- ARCH-34 pre_check execution ------------------------------------------


def _tcf_with_pre_check() -> CabTcf:
    """Sample TCF with pre_check rows for both polarities."""
    return CabTcf(
        change_id="precheck_lab_test",
        title="ARCH-34 lab pre_check execution",
        created_by="sim",
        created_at=datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC),
        risk_class="low",
        intent=Intent(type="ebgp_direct", lab_subnet="192.0.2.0/30"),
        devices=[
            Device(name="R1", platform="cisco_ios",
                   prod_loopback="1.1.1.1", prod_asn=65000),
            Device(name="R4", platform="cisco_ios",
                   prod_loopback="4.4.4.4", prod_asn=65001),
        ],
        implementation=[
            CliBlock(device="R1", phase=1, cli=["router bgp 65000"]),
        ],
        pre_check=[
            # must_match=False: 'via ' must NOT appear in route output
            PreCheck(device="R1", check_id="PR-R1-subnet-clear",
                     description="lab_subnet must not be routed",
                     command="show ip route 192.0.2.0/30",
                     expected_pattern="via ", must_match=False),
            # must_match=True: 'unassigned' must appear in intf brief
            PreCheck(device="R1", check_id="PR-R1-intf-free",
                     description="interface must not have IP",
                     command="show ip interface brief GigabitEthernet0/2",
                     expected_pattern="unassigned", must_match=True),
        ],
        post_check=[
            PostCheck(device="R1", check_id="bgp_up_r1",
                      description="BGP neighbor up on R1",
                      command="show ip bgp summary",
                      expected_pattern="established"),
        ],
        tvt=[TvtRow(test_id="bgp_up_r1", description="BGP up R1",
                    expected="Established", severity="blocker")],
        required_tests=["bgp_up_r1"],
    )


def test_lab_executes_pre_check_with_must_match_polarity(
    tmp_path, monkeypatch
):
    """Lab Phase 4.5 runs every pre_check, applies must_match polarity,
    and surfaces results in pre_check_results."""
    spec = tmp_path / "spec.tcf.yaml"
    tcf_emit(_tcf_with_pre_check(), spec)

    exec_calls: list[str] = []

    def _fake(service: str, *, method: str = "GET", path: str = "",
             params: dict | None = None, body: dict | None = None,
             confirmed: bool = False, timeout: float = 30.0):
        if service != "containerlab":
            raise AssertionError(f"unexpected service: {service}")
        if method == "POST" and path == "/api/v1/labs":
            return {"status": "deployed", "lab": body.get("name")}
        if method == "POST" and "/exec" in path:
            container = (params or {}).get("nodeFilter", "unknown")
            cmd = (body or {}).get("command", "")
            # _exec_check wraps sr_cli in `bash -c 'echo <b64> | base64
            # -d | sr_cli ...'`; decode so substring matching sees the
            # underlying command.
            if "base64 -d" in cmd:
                import base64 as _b64, re as _re
                m = _re.search(r"echo\s+([A-Za-z0-9+/=]+)\s*\|", cmd)
                if m:
                    try:
                        cmd = cmd + " " + _b64.b64decode(m.group(1)).decode()
                    except Exception:
                        pass
            exec_calls.append(cmd)
            # Lab fresh, so no routes -> empty routing table response
            # (simulating "% Network not in table" semantics)
            if "route" in cmd:
                return _mk_clab_exec_response(container, "% Subnet not in table")
            # Interface brief: simulate unassigned
            if "interface" in cmd or "intf" in cmd:
                return _mk_clab_exec_response(
                    container, "GigabitEthernet0/2  unassigned  YES  unset")
            # BGP summary post_check: established
            return _mk_clab_exec_response(
                container, "172.16.99.2 established")
        if method == "DELETE" and path.startswith("/api/v1/labs/"):
            return {"status": "destroyed"}
        if method == "GET" and path.startswith("/api/v1/labs/"):
            raise RuntimeError("404 not found")
        return {}

    monkeypatch.setattr("olav.platform.services.client.service_call", _fake)

    out = validate_tcf_in_lab(
        spec, deploy_wait_seconds=0,
        post_commit_wait_seconds=0, convergence_wait_seconds=0,
    )

    assert out["status"] == "ok"
    assert "pre_check_results" in out, "lab must surface pre_check results"
    assert len(out["pre_check_results"]) == 2

    # subnet-clear: must_match=False, pattern 'via ' absent in '% Subnet not in
    # table' -> match=False -> passed=True (absence proves clear)
    sc = next(r for r in out["pre_check_results"]
              if r["check_id"] == "PR-R1-subnet-clear")
    assert sc["must_match"] is False
    assert sc["passed"] is True, (
        f"subnet-clear: pattern absent should pass; got {sc!r}"
    )

    # intf-free: must_match=True, pattern 'unassigned' present -> passed=True
    iff = next(r for r in out["pre_check_results"]
               if r["check_id"] == "PR-R1-intf-free")
    assert iff["must_match"] is True
    assert iff["passed"] is True

    # Each pre_check result carries the exec'd command (post-translation)
    assert all("command_executed" in r for r in out["pre_check_results"])

    # Journal contains a verify_pre_check entry
    assert any(
        j.get("step") == "verify_pre_check"
        for j in out["journal"]
    ), f"verify_pre_check missing from journal: {out['journal']!r}"


def test_lab_pre_check_failure_does_not_block_post_check(
    tmp_path, monkeypatch
):
    """If a pre_check fails (informational in lab), post_check still
    runs and verdict is determined by post_check alone."""
    spec = tmp_path / "spec.tcf.yaml"
    tcf_emit(_tcf_with_pre_check(), spec)

    def _fake(service: str, *, method: str = "GET", path: str = "",
             params: dict | None = None, body: dict | None = None,
             confirmed: bool = False, timeout: float = 30.0):
        if method == "POST" and path == "/api/v1/labs":
            return {"status": "deployed", "lab": body.get("name")}
        if method == "POST" and "/exec" in path:
            container = (params or {}).get("nodeFilter", "unknown")
            cmd = (body or {}).get("command", "")
            # _exec_check wraps sr_cli in `bash -c 'echo <b64> | base64
            # -d | sr_cli ...'`; decode so substring matching sees the
            # underlying command.
            if "base64 -d" in cmd:
                import base64 as _b64, re as _re
                m = _re.search(r"echo\s+([A-Za-z0-9+/=]+)\s*\|", cmd)
                if m:
                    try:
                        cmd = cmd + " " + _b64.b64decode(m.group(1)).decode()
                    except Exception:
                        pass
            # Make pre_checks FAIL: route command has 'via X.X.X.X' present
            if "route" in cmd:
                return _mk_clab_exec_response(
                    container, "S    192.0.2.0/30 [1/0] via 10.0.0.1")
            if "interface" in cmd:
                # Interface configured: 'unassigned' missing, so must_match=True
                # check fails
                return _mk_clab_exec_response(
                    container, "GigabitEthernet0/2  10.99.0.1  YES  manual")
            # post_check still passes
            return _mk_clab_exec_response(container, "172.16.99.2 established")
        if method == "DELETE" and path.startswith("/api/v1/labs/"):
            return {"status": "destroyed"}
        if method == "GET" and path.startswith("/api/v1/labs/"):
            raise RuntimeError("404 not found")
        return {}

    monkeypatch.setattr("olav.platform.services.client.service_call", _fake)

    out = validate_tcf_in_lab(
        spec, deploy_wait_seconds=0,
        post_commit_wait_seconds=0, convergence_wait_seconds=0,
    )

    assert out["status"] == "ok"
    # Both pre_checks should fail
    assert all(not r["passed"] for r in out["pre_check_results"])
    # But post_check still ran and passed → verdict=PASS (informational sema)
    assert out["verdict"] == "PASS"
    assert all(r["passed"] for r in out["post_check_results"])

"""TCF spec ↔ lab diff helper tests.

Covers:
  * TVT match logic (substring + regex, case-insensitive)
  * Overall verdict derivation (blocker FAIL → FAIL; warn-only → PASS-WITH-WARNINGS)
  * Required-test compliance tracking
  * Silent-override detection (lab journal asns ≠ spec.devices.prod_asn,
    AS numbers in spec CLI not matching any prod_asn)
  * Markdown rendering
"""
from __future__ import annotations

from datetime import UTC, datetime

from olav.core.cab import (
    CabTcf,
    CliBlock,
    Device,
    ExecutionRecord,
    Intent,
    JournalEntry,
    PostCheck,
    TvtRow,
    tcf_diff_spec_vs_lab,
)
from olav.core.cab.tcf_diff import _matches


def _ebgp_tcf(
    *,
    tvt: list[TvtRow] | None = None,
    lab: ExecutionRecord | None = None,
    implementation: list[CliBlock] | None = None,
    required_tests: list[str] | None = None,
) -> CabTcf:
    return CabTcf(
        change_id="cab_diff_test",
        title="Diff test",
        created_by="ops-analyze",
        created_at=datetime.now(UTC),
        risk_class="low",
        intent=Intent(type="ebgp_direct", lab_subnet="172.16.99.0/30"),
        devices=[
            Device(name="R1", platform="juniper_junos", prod_loopback="1.1.1.1", prod_asn=65000),
            Device(name="R4", platform="cisco_ios", prod_loopback="4.4.4.4", prod_asn=65001),
        ],
        implementation=implementation or [],
        tvt=tvt or [],
        required_tests=required_tests or [],
        lab=lab or ExecutionRecord(),
    )


# --- _matches ---------------------------------------------------------------


def test_matches_substring_case_insensitive():
    assert _matches("BGP Established", "established") is True
    assert _matches("BGP Established", "ESTABLISHED") is True
    assert _matches("BGP active", "established") is False


def test_matches_regex_prefix():
    assert _matches("Rx 5 routes", "re:^Rx \\d+") is True
    assert _matches("0 routes", "re:^Rx \\d+") is False


def test_matches_actual_none():
    assert _matches(None, "anything") is False


# --- TVT diffs --------------------------------------------------------------


def test_diff_pass_when_actual_matches_expected():
    tcf = _ebgp_tcf(
        tvt=[
            TvtRow(
                test_id="T1",
                description="BGP up",
                expected="Established",
                severity="blocker",
                actual_lab="state=Established",
                status="PASS",
            ),
        ],
        required_tests=["T1"],
        lab=ExecutionRecord(verdict="PASS"),
    )
    result = tcf_diff_spec_vs_lab(tcf)
    assert result.overall_verdict == "PASS"
    assert result.all_required_pass
    assert result.tvt_diffs[0].matches is True


def test_diff_fail_when_blocker_test_fails():
    tcf = _ebgp_tcf(
        tvt=[
            TvtRow(
                test_id="T1",
                description="BGP up",
                expected="Established",
                severity="blocker",
                actual_lab="state=active",  # NOT matching
                status="FAIL",
            ),
        ],
        required_tests=["T1"],
        lab=ExecutionRecord(verdict="FAIL"),
    )
    result = tcf_diff_spec_vs_lab(tcf)
    assert result.overall_verdict == "FAIL"
    assert result.all_required_pass is False


def test_diff_pass_with_warnings_when_only_non_blocker_fails():
    tcf = _ebgp_tcf(
        tvt=[
            TvtRow(
                test_id="T1",
                description="BGP up",
                expected="Established",
                severity="blocker",
                actual_lab="Established",
                status="PASS",
            ),
            TvtRow(
                test_id="T2",
                description="Optional metric",
                expected="100",
                severity="warn",
                actual_lab="200",   # mismatch
                status="FAIL",
            ),
        ],
        required_tests=["T1"],
        lab=ExecutionRecord(verdict="PASS"),
    )
    result = tcf_diff_spec_vs_lab(tcf)
    assert result.overall_verdict == "PASS-WITH-WARNINGS"
    assert result.all_required_pass is True


def test_diff_required_test_missing_from_tvt_marks_noncompliant():
    """If required_tests mentions T_GHOST but tvt has only T1,
    compliance for T_GHOST is False.
    Note: schema-level FK validator already prevents this at write
    time — but the diff should be defensive in case a TCF is
    constructed differently.
    """
    # We can't construct via Pydantic with the FK violation; instead
    # mutate after construction.
    tcf = _ebgp_tcf(
        tvt=[TvtRow(test_id="T1", description="x", expected="y", severity="blocker")],
        required_tests=["T1"],
    )
    tcf.required_tests.append("T_GHOST")  # bypass validator post-construction
    result = tcf_diff_spec_vs_lab(tcf)
    assert result.required_test_compliance["T_GHOST"] is False


# --- Silent-override detection ---------------------------------------------


def test_silent_override_lab_asns_differ_from_prod_asn():
    """Lab passed asns=[65000, 65999] but spec.devices.prod_asn=[65000, 65001]."""
    tcf = _ebgp_tcf(
        lab=ExecutionRecord(
            verdict="PASS",
            journal=[
                JournalEntry(
                    step="generate_srl_lab_config",
                    args={"nodes": ["R1", "R4"], "asns": [65000, 65999]},
                ),
            ],
        ),
    )
    result = tcf_diff_spec_vs_lab(tcf)
    overrides = result.silent_overrides
    assert any(o.field == "R4.asn" and o.spec_value == 65001 and o.lab_value == 65999
               for o in overrides), f"got: {overrides}"


def test_silent_override_unknown_asn_in_cli():
    """spec implementation CLI mentions AS65999 but neither device's
    prod_asn is 65999. Suggests a typo in the spec the lab silently
    bypassed."""
    tcf = _ebgp_tcf(
        implementation=[
            CliBlock(
                device="R4",
                phase=1,
                cli=["router bgp 65001", " neighbor 1.1.1.1 remote-as 65999"],
            ),
        ],
        lab=ExecutionRecord(
            verdict="PASS",
            journal=[
                JournalEntry(
                    step="generate_srl_lab_config",
                    args={"nodes": ["R1", "R4"], "asns": [65000, 65001]},
                ),
            ],
        ),
    )
    result = tcf_diff_spec_vs_lab(tcf)
    cli_overrides = [o for o in result.silent_overrides if "cli" in o.field]
    assert cli_overrides, f"expected a CLI override for AS 65999, got: {result.silent_overrides}"
    assert any(o.spec_value == 65999 for o in cli_overrides)


def test_no_overrides_when_spec_and_lab_consistent():
    """All AS numbers in CLI match prod_asn; lab journal asns match
    devices."""
    tcf = _ebgp_tcf(
        implementation=[
            CliBlock(
                device="R4",
                phase=1,
                cli=["router bgp 65001", " neighbor 1.1.1.1 remote-as 65000"],
            ),
        ],
        lab=ExecutionRecord(
            verdict="PASS",
            journal=[
                JournalEntry(
                    step="generate_srl_lab_config",
                    args={"nodes": ["R1", "R4"], "asns": [65000, 65001]},
                ),
            ],
        ),
    )
    result = tcf_diff_spec_vs_lab(tcf)
    assert result.silent_overrides == []


# --- Markdown rendering -----------------------------------------------------


def test_to_markdown_includes_tvt_table():
    tcf = _ebgp_tcf(
        tvt=[
            TvtRow(
                test_id="T1",
                description="BGP up",
                expected="Established",
                severity="blocker",
                actual_lab="Established",
                status="PASS",
            ),
        ],
        required_tests=["T1"],
        lab=ExecutionRecord(verdict="PASS"),
    )
    md = tcf_diff_spec_vs_lab(tcf).to_markdown()
    assert "Spec ↔ Lab diff" in md
    assert "T1" in md
    assert "BGP up" in md
    assert "Established" in md


def test_to_markdown_includes_silent_override_section_when_present():
    tcf = _ebgp_tcf(
        implementation=[
            CliBlock(device="R4", phase=1, cli=[" neighbor 1.1.1.1 remote-as 65999"]),
        ],
        lab=ExecutionRecord(
            verdict="PASS",
            journal=[
                JournalEntry(
                    step="generate_srl_lab_config",
                    args={"nodes": ["R1", "R4"], "asns": [65000, 65001]},
                ),
            ],
        ),
    )
    md = tcf_diff_spec_vs_lab(tcf).to_markdown()
    assert "Silent Overrides" in md
    assert "65999" in md


def test_to_markdown_handles_empty_tcf():
    tcf = _ebgp_tcf()  # no tvt, no overrides
    md = tcf_diff_spec_vs_lab(tcf).to_markdown()
    assert "no TVT rows" in md


# --- R94 step verdicts ------------------------------------------------------


def _ebgp_tcf_with_lab_evidence(
    *,
    impl_lab: list[CliBlock] | None = None,
    rb_lab: list[CliBlock] | None = None,
    pc_lab: list[PostCheck] | None = None,
    tvt: list[TvtRow] | None = None,
) -> CabTcf:
    """Build a TCF with both spec lists and lab.*_lab fields populated."""
    return CabTcf(
        change_id="cab_step_verdict_test",
        title="step verdict",
        created_by="ops-analyze",
        created_at=datetime.now(UTC),
        intent=Intent(type="ebgp_direct"),
        devices=[
            Device(name="R1", platform="juniper_junos", prod_asn=65000),
            Device(name="R4", platform="cisco_ios", prod_asn=65001),
        ],
        implementation=[
            CliBlock(device="R1", phase=1, cli=["set ... R1 cmd"]),
            CliBlock(device="R4", phase=1, cli=["set ... R4 cmd"]),
        ],
        rollback=[
            CliBlock(device="R1", phase="rb1", cli=["delete ... R1"]),
            CliBlock(device="R4", phase="rb1", cli=["delete ... R4"]),
        ],
        post_check=[
            PostCheck(device="R1", check_id="bgp_up", description="BGP up",
                      command="show bgp summary", expected_pattern="Established"),
        ],
        tvt=tvt or [
            TvtRow(test_id="T1", description="BGP", expected="Established",
                   severity="blocker", actual_lab="Established", status="PASS"),
        ],
        lab=ExecutionRecord(
            verdict="PASS",
            implementation_lab=impl_lab or [],
            rollback_lab=rb_lab or [],
            post_check_lab=pc_lab or [],
        ),
    )


def test_step_verdicts_paired_blocks_emit_no_verdict():
    """R94.2 policy: structurally-paired implementation / rollback blocks
    emit NO verdict — semantic judgement is the agent's job. Only TVT
    (real pattern match) and post_check (real string equality / form
    diff) get verdicts from the deterministic layer."""
    tcf = _ebgp_tcf_with_lab_evidence(
        impl_lab=[
            CliBlock(device="r1", phase=1, cli=["set / ..."]),
            CliBlock(device="r4", phase=1, cli=["set / ..."]),
        ],
        rb_lab=[
            CliBlock(device="r1", phase="rb1", cli=["delete / ..."]),
            CliBlock(device="r4", phase="rb1", cli=["delete / ..."]),
        ],
        pc_lab=[
            PostCheck(device="r1", check_id="bgp_up", description="lab",
                      command="sr_cli show ...", expected_pattern="established"),
        ],
    )
    res = tcf_diff_spec_vs_lab(tcf)
    by_verdict: dict[str, int] = {}
    for v in res.step_verdicts:
        by_verdict[v.verdict] = by_verdict.get(v.verdict, 0) + 1
    # No "approved" from impl/rollback pairing — those are deferred to agent.
    impl_rb_verdicts = [
        v for v in res.step_verdicts
        if v.spec_ref and (
            v.spec_ref.startswith("implementation[")
            or v.spec_ref.startswith("rollback[")
        )
    ]
    assert impl_rb_verdicts == []
    # post_check: command form differs → 1 info
    assert by_verdict.get("info", 0) == 1
    # tvt: pattern matches → 1 approved
    assert by_verdict.get("approved", 0) == 1
    assert "missing" not in by_verdict
    assert "extra" not in by_verdict


def test_step_verdicts_missing_rollback_flagged():
    tcf = _ebgp_tcf_with_lab_evidence(
        impl_lab=[
            CliBlock(device="r1", phase=1, cli=["set"]),
            CliBlock(device="r4", phase=1, cli=["set"]),
        ],
        rb_lab=[
            CliBlock(device="r1", phase="rb1", cli=["delete"]),
            # R4 rollback intentionally missing
        ],
    )
    res = tcf_diff_spec_vs_lab(tcf)
    missing = [v for v in res.step_verdicts if v.verdict == "missing"]
    rb_missing = [
        v for v in missing
        if v.spec_ref and v.spec_ref.startswith("rollback[")
    ]
    assert len(rb_missing) == 1
    assert "r4" in rb_missing[0].reason.lower()


def test_step_verdicts_extra_lab_block_flagged():
    tcf = _ebgp_tcf_with_lab_evidence(
        impl_lab=[
            CliBlock(device="r1", phase=1, cli=["set"]),
            CliBlock(device="r4", phase=1, cli=["set"]),
            CliBlock(device="r99", phase=1, cli=["set"]),  # not in spec
        ],
    )
    res = tcf_diff_spec_vs_lab(tcf)
    extras = [v for v in res.step_verdicts if v.verdict == "extra"]
    assert any(
        e.lab_ref and e.lab_ref.startswith("implementation_lab[")
        for e in extras
    )


def test_step_verdicts_tvt_rejected_when_pattern_mismatch():
    tcf = _ebgp_tcf_with_lab_evidence(
        tvt=[
            TvtRow(test_id="T1", description="BGP", expected="Established",
                   severity="blocker", actual_lab="Idle", status="FAIL"),
        ],
    )
    res = tcf_diff_spec_vs_lab(tcf)
    tvt_v = [v for v in res.step_verdicts if v.spec_ref == "tvt[T1]"]
    assert len(tvt_v) == 1
    assert tvt_v[0].verdict == "rejected"


def test_step_verdicts_render_in_markdown():
    """Markdown render shows step verdicts when present. With the
    R94.2 policy (paired impl/rollback emit no verdict), this test
    builds a scenario where R4 has no lab counterpart → emits missing
    for implementation[1] / rollback[1]."""
    tcf = _ebgp_tcf_with_lab_evidence(
        impl_lab=[CliBlock(device="r1", phase=1, cli=["set"])],
    )
    md = tcf_diff_spec_vs_lab(tcf).to_markdown()
    assert "Step Verdicts" in md
    # R4 has no impl_lab counterpart → missing verdict referencing it
    assert "implementation[1]" in md
    assert "missing" in md.lower()

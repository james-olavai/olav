"""TCF spec ↔ lab structured diff.

After ops-lab fills in ``tcf.lab.*`` and ``tcf.tvt[*].actual_lab``,
this module produces a structured comparison surfacing:

  * TVT pass/fail per test row (expected vs actual_lab)
  * Severity-weighted overall verdict (any blocker FAIL → FAIL)
  * Silent overrides — when lab journal args differ from what the
    spec implementation would have suggested (e.g. lab passed
    ``asns=[65000, 65001]`` but spec implementation_json contained
    a peer-as typo)
  * Required-test compliance — which required_tests are PASS

Returns a typed ``TcfDiffResult`` with structured rows + a markdown
rendering helper for human-facing reports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any  # noqa: F401  (Any used in helper signatures)

from .tcf_schema import CabTcf, StepVerdict


@dataclass
class TvtDiff:
    test_id: str
    description: str
    expected: str
    actual_lab: str | None
    severity: str
    status: str
    matches: bool                # True iff actual_lab matches expected pattern


@dataclass
class SilentOverride:
    """One spec-vs-lab divergence flagged as a possible silent override.

    Example: spec says peer-as=65999 (typo) in implementation CLI but
    lab journal shows generate_srl_lab_config was called with
    asns=[65000, 65001] — lab silently fixed the typo.
    """
    field: str                   # e.g. "R4.peer_as"
    spec_value: str | int | None
    lab_value: str | int | None
    severity: str = "warn"       # "error" | "warn" | "info"
    reason: str = ""


@dataclass
class TcfDiffResult:
    change_id: str
    lab_verdict: str
    overall_verdict: str          # PASS / FAIL / BLOCKED, derived from severity weighted TVT
    tvt_diffs: list[TvtDiff] = field(default_factory=list)
    required_test_compliance: dict[str, bool] = field(default_factory=dict)
    silent_overrides: list[SilentOverride] = field(default_factory=list)
    step_verdicts: list[StepVerdict] = field(default_factory=list)

    @property
    def all_required_pass(self) -> bool:
        return all(self.required_test_compliance.values()) if self.required_test_compliance else True

    def to_markdown(self) -> str:
        """Render the diff as a markdown block — for embedding in
        writer-rendered narrative or appending to lab reports."""
        lines: list[str] = []
        lines.append(f"## Spec ↔ Lab diff for `{self.change_id}`")
        lines.append("")
        lines.append(
            f"**Lab verdict**: `{self.lab_verdict}`   "
            f"**Overall verdict**: `{self.overall_verdict}`   "
            f"**Required tests pass**: "
            f"{'✅ all' if self.all_required_pass else '❌ some failing'}"
        )
        lines.append("")

        if self.tvt_diffs:
            lines.append("### Test Verification (TVT)")
            lines.append("")
            lines.append(
                "| Test | Description | Expected | Actual (lab) | "
                "Severity | Status | Match |"
            )
            lines.append(
                "|---|---|---|---|---|---|---|"
            )
            for d in self.tvt_diffs:
                actual = d.actual_lab if d.actual_lab is not None else "—"
                match_icon = "✅" if d.matches else "❌"
                lines.append(
                    f"| `{d.test_id}` | {d.description} | {d.expected} | "
                    f"{actual} | {d.severity} | {d.status} | {match_icon} |"
                )
            lines.append("")

        if self.silent_overrides:
            lines.append("### Silent Overrides (spec ≠ lab actions)")
            lines.append("")
            lines.append("| Field | Spec value | Lab value | Severity | Reason |")
            lines.append("|---|---|---|---|---|")
            for o in self.silent_overrides:
                sev_icon = {"error": "🔴", "warn": "🟡", "info": "ℹ️"}.get(
                    o.severity, "ℹ️"
                )
                lines.append(
                    f"| `{o.field}` | {o.spec_value} | {o.lab_value} | "
                    f"{sev_icon} {o.severity} | {o.reason} |"
                )
            lines.append("")

        if self.step_verdicts:
            lines.append("### Step Verdicts (sim ↔ lab cross-verification)")
            lines.append("")
            lines.append("| Spec ref | Lab ref | Verdict | Reason |")
            lines.append("|---|---|---|---|")
            for v in self.step_verdicts:
                v_icon = {
                    "approved": "✅",
                    "rejected": "❌",
                    "missing": "⚠️",
                    "extra": "➕",
                    "info": "ℹ️",
                }.get(v.verdict, "•")
                lines.append(
                    f"| `{v.spec_ref or '—'}` | `{v.lab_ref or '—'}` | "
                    f"{v_icon} {v.verdict} | {v.reason} |"
                )
            lines.append("")

        if (
            not self.tvt_diffs
            and not self.silent_overrides
            and not self.step_verdicts
        ):
            lines.append("(no TVT rows, step verdicts, or overrides recorded)")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Match logic
# ---------------------------------------------------------------------------


def _matches(actual: str | None, expected_pattern: str) -> bool:
    """Whether ``actual`` matches ``expected_pattern``.

    Convention:
      * bare string → substring match (case-insensitive)
      * ``re:<regex>`` prefix → regex match (case-insensitive)
    """
    if actual is None:
        return False
    if expected_pattern.startswith("re:"):
        try:
            return bool(re.search(expected_pattern[3:], actual, re.IGNORECASE))
        except re.error:
            return False
    return expected_pattern.lower() in actual.lower()


# ---------------------------------------------------------------------------
# Silent-override detection (heuristic, conservative)
# ---------------------------------------------------------------------------


_AS_PATTERN = re.compile(r"\b(?:peer-as|remote-as|local-as|peer_as)\s+(\d+)\b", re.I)
_IP_PATTERN = re.compile(r"(?<![\d.])(\d+\.\d+\.\d+\.\d+)(?:/\d+)?(?![\d.])")


def _extract_spec_asns(tcf: CabTcf) -> dict[str, list[int]]:
    """Pull AS numbers seen in implementation CLI, grouped by device.

    Used to detect cases where the spec's CLI mentions an AS number
    that doesn't match the lab journal's asns input.
    """
    out: dict[str, list[int]] = {}
    for block in tcf.implementation:
        d = block.device
        for line in block.cli:
            for m in _AS_PATTERN.findall(line):
                try:
                    out.setdefault(d, []).append(int(m))
                except ValueError:
                    pass
    return out


def _detect_silent_overrides(tcf: CabTcf) -> list[SilentOverride]:
    """Compare spec implementation against lab journal args; flag
    suspected silent overrides.

    Currently checks two classes (more can be added):

    1. **AS number typo correction** — spec implementation CLI
       mentions an AS that doesn't appear in the device's
       prod_asn or in the peer's prod_asn (could indicate a typo
       the lab silently bypassed).

    2. **Lab journal asns vs device.prod_asn** — the lab's R89 call
       should have used per-device prod_asn from the spec; if it
       didn't, that's a silent override.
    """
    overrides: list[SilentOverride] = []
    if not tcf.lab.journal:
        return overrides

    # Find the generate_srl_lab_config journal entry, if any
    srl_entry = None
    for j in tcf.lab.journal:
        if j.step in {"generate_srl_lab_config", "tcf_to_r89_args"}:
            srl_entry = j
            break

    # Build expected AS list from devices
    expected_asns = [d.prod_asn for d in tcf.devices if d.prod_asn is not None]
    expected_node_asns = {
        d.name: d.prod_asn for d in tcf.devices if d.prod_asn is not None
    }

    # 1. Lab's actual asns vs spec.devices.prod_asn
    if srl_entry:
        lab_asns = srl_entry.args.get("asns")
        lab_nodes = srl_entry.args.get("nodes")
        if isinstance(lab_asns, list) and isinstance(lab_nodes, list):
            for n, a in zip(lab_nodes, lab_asns, strict=False):
                spec_a = expected_node_asns.get(n)
                if spec_a is not None and int(a) != int(spec_a):
                    overrides.append(SilentOverride(
                        field=f"{n}.asn",
                        spec_value=spec_a,
                        lab_value=int(a),
                        severity="error",
                        reason=(
                            f"lab passed asn={a} for device {n} but spec "
                            f"declared prod_asn={spec_a} — fix one or the other"
                        ),
                    ))

    # 2. AS numbers in CLI vs declared prod_asn / peer prod_asn
    cli_asns = _extract_spec_asns(tcf)
    for device, asn_list in cli_asns.items():
        own_asn = expected_node_asns.get(device)
        peer_asns = [a for n, a in expected_node_asns.items() if n != device]
        for a in asn_list:
            if a == own_asn:
                continue
            if a in peer_asns:
                continue
            overrides.append(SilentOverride(
                field=f"{device}.cli",
                spec_value=a,
                lab_value=f"expected {own_asn} (own) or {peer_asns} (peer)",
                severity="warn",
                reason=(
                    f"AS number {a} appears in {device}'s implementation CLI "
                    f"but doesn't match own prod_asn or any peer's prod_asn — "
                    f"possible typo in spec"
                ),
            ))

    return overrides


# ---------------------------------------------------------------------------
# Step-level verdicts (R94)
# ---------------------------------------------------------------------------


def _diff_cli_blocks(
    spec_blocks: list[Any],
    lab_blocks: list[Any],
    *,
    spec_kind: str,
    lab_kind: str,
) -> list[StepVerdict]:
    """Structural-only diff for sim vs lab CLI blocks.

    **Policy (R94.2)**: this function emits verdicts ONLY for structural
    gaps — ``missing`` (spec has a block for a device, lab didn't push
    one) and ``extra`` (lab pushed a block for a device that's not in
    spec). It deliberately does **not** emit ``approved`` when the two
    sides happen to share a device name, because device-name pairing is
    not a semantic judgement — Junos / IOS prod CLI vs SRL lab CLI can
    differ in ASN, neighbor IP, policy, or even change type while
    sharing the same node name.

    Semantic verdicts (``approved`` / ``rejected`` / ``info``) for
    paired blocks must come from the agent reading the TCF and writing
    back via ``tcf_record_lab_run(step_verdicts=...)``. The agent has
    sandbox file tools (Read) and the full bilateral payload is on
    disk; trying to fake semantic judgement in Python here would just
    ship false positives to CAB.
    """
    out: list[StepVerdict] = []

    spec_by_dev: dict[str, list[tuple[int, Any]]] = {}
    for i, block in enumerate(spec_blocks):
        spec_by_dev.setdefault(block.device.lower(), []).append((i, block))

    lab_by_dev: dict[str, list[tuple[int, Any]]] = {}
    for i, block in enumerate(lab_blocks):
        lab_by_dev.setdefault(block.device.lower(), []).append((i, block))

    for dev, spec_items in spec_by_dev.items():
        if lab_by_dev.get(dev):
            # Paired structurally — semantic verdict deferred to agent.
            continue
        for spec_idx, spec_block in spec_items:
            out.append(StepVerdict(
                spec_ref=f"{spec_kind}[{spec_idx}]",
                lab_ref=None,
                verdict="missing",
                reason=(
                    f"spec has {spec_kind} block for device "
                    f"{spec_block.device!r} but lab didn't record any "
                    f"{lab_kind} for it"
                ),
            ))

    spec_devs = set(spec_by_dev.keys())
    for dev, lab_items in lab_by_dev.items():
        if dev in spec_devs:
            continue
        for lab_idx, lab_block in lab_items:
            out.append(StepVerdict(
                spec_ref=None,
                lab_ref=f"{lab_kind}[{lab_idx}]",
                verdict="extra",
                reason=(
                    f"lab ran {lab_kind} on device {lab_block.device!r} "
                    f"that's not in the spec {spec_kind} list"
                ),
            ))

    return out


def _diff_post_checks(tcf: CabTcf) -> list[StepVerdict]:
    """Match each spec post_check to a lab post_check_lab entry by
    (lower-case device, check_id-prefix).

    The lab translates the spec's prod-form command (``show bgp summary``
    on Junos) into the lab-form (``sr_cli show network-instance default
    protocols bgp neighbor``) so the verdict is informational by default
    when both sides exist — the operator confirms semantic equivalence.
    """
    out: list[StepVerdict] = []

    spec_by_key: dict[tuple[str, str], tuple[int, Any]] = {}
    for i, c in enumerate(tcf.post_check):
        spec_by_key[(c.device.lower(), c.check_id)] = (i, c)

    lab_by_dev: dict[str, list[tuple[int, Any]]] = {}
    for i, c in enumerate(tcf.lab.post_check_lab):
        lab_by_dev.setdefault(c.device.lower(), []).append((i, c))

    used_lab_idx: set[tuple[str, int]] = set()
    for (dev, check_id), (spec_idx, spec_check) in spec_by_key.items():
        match: tuple[int, Any] | None = None
        for lab_idx, lab_check in lab_by_dev.get(dev, []):
            if (dev, lab_idx) in used_lab_idx:
                continue
            if lab_check.check_id == check_id or lab_check.check_id.startswith(
                check_id
            ):
                match = (lab_idx, lab_check)
                used_lab_idx.add((dev, lab_idx))
                break
        if match is None:
            for lab_idx, lab_check in lab_by_dev.get(dev, []):
                if (dev, lab_idx) in used_lab_idx:
                    continue
                match = (lab_idx, lab_check)
                used_lab_idx.add((dev, lab_idx))
                break
        if match is not None:
            lab_idx, lab_check = match
            same_cmd = lab_check.command.strip() == spec_check.command.strip()
            verdict = "approved" if same_cmd else "info"
            reason = (
                "command identical"
                if same_cmd
                else (
                    f"lab translated command form: spec="
                    f"{spec_check.command!r}, lab={lab_check.command!r}"
                )
            )
            out.append(StepVerdict(
                spec_ref=f"post_check[{check_id}]",
                lab_ref=f"post_check_lab[{lab_idx}]",
                verdict=verdict,
                reason=reason,
            ))
        else:
            out.append(StepVerdict(
                spec_ref=f"post_check[{check_id}]",
                lab_ref=None,
                verdict="missing",
                reason=(
                    f"spec post_check {check_id!r} on {spec_check.device!r} "
                    f"has no lab counterpart"
                ),
            ))

    spec_keys_by_dev: dict[str, set[str]] = {}
    for (dev, check_id), _ in spec_by_key.items():
        spec_keys_by_dev.setdefault(dev, set()).add(check_id)
    for dev, lab_items in lab_by_dev.items():
        for lab_idx, lab_check in lab_items:
            if (dev, lab_idx) in used_lab_idx:
                continue
            out.append(StepVerdict(
                spec_ref=None,
                lab_ref=f"post_check_lab[{lab_idx}]",
                verdict="extra",
                reason=(
                    f"lab post_check_lab on {lab_check.device!r} "
                    f"({lab_check.check_id!r}) has no spec counterpart"
                ),
            ))

    return out


def _diff_tvt_rows(tvt_diffs: list[TvtDiff]) -> list[StepVerdict]:
    """One StepVerdict per TVT row, derived from the existing TvtDiff."""
    out: list[StepVerdict] = []
    for d in tvt_diffs:
        if d.matches and d.status == "PASS":
            verdict = "approved"
            reason = f"actual {d.actual_lab!r} matches expected {d.expected!r}"
        elif d.matches:
            verdict = "info"
            reason = f"pattern matched but status={d.status}"
        else:
            verdict = "rejected"
            reason = (
                f"actual {d.actual_lab!r} does not match expected "
                f"{d.expected!r} (severity {d.severity})"
            )
        out.append(StepVerdict(
            spec_ref=f"tvt[{d.test_id}]",
            lab_ref=f"tvt[{d.test_id}].actual_lab",
            verdict=verdict,
            reason=reason,
        ))
    return out


def _compute_step_verdicts(tcf: CabTcf, tvt_diffs: list[TvtDiff]) -> list[StepVerdict]:
    """Build the full per-step approve/reject ledger for the lab run."""
    verdicts: list[StepVerdict] = []
    verdicts.extend(_diff_cli_blocks(
        list(tcf.implementation),
        list(tcf.lab.implementation_lab),
        spec_kind="implementation",
        lab_kind="implementation_lab",
    ))
    verdicts.extend(_diff_cli_blocks(
        list(tcf.rollback),
        list(tcf.lab.rollback_lab),
        spec_kind="rollback",
        lab_kind="rollback_lab",
    ))
    verdicts.extend(_diff_post_checks(tcf))
    verdicts.extend(_diff_tvt_rows(tvt_diffs))
    return verdicts


# ---------------------------------------------------------------------------
# Top-level diff
# ---------------------------------------------------------------------------


def tcf_diff_spec_vs_lab(tcf: CabTcf) -> TcfDiffResult:
    """Compute the structured spec ↔ lab diff for a TCF.

    The TCF must have already been touched by the lab (i.e. ``tcf.lab``
    has a non-PENDING verdict and TVT rows have actual_lab populated).
    A diff on a still-PENDING TCF yields a result with empty
    overall_verdict and unmatched TVT rows — useful for sanity-checking
    a lab run mid-flight, but the typical caller invokes after lab
    completion.
    """
    tvt_diffs: list[TvtDiff] = []
    blocker_fail = False
    any_fail = False

    for row in tcf.tvt:
        match = _matches(row.actual_lab, row.expected)
        tvt_diffs.append(TvtDiff(
            test_id=row.test_id,
            description=row.description,
            expected=row.expected,
            actual_lab=row.actual_lab,
            severity=row.severity,
            status=row.status,
            matches=match,
        ))
        if not match or row.status == "FAIL":
            any_fail = True
            if row.severity == "blocker":
                blocker_fail = True

    # Required-test compliance
    required = set(tcf.required_tests)
    required_compliance: dict[str, bool] = {}
    for d in tvt_diffs:
        if d.test_id in required:
            required_compliance[d.test_id] = (
                d.matches and d.status == "PASS"
            )
    # Required tests not in tvt at all → automatic non-compliant
    for r in required - {d.test_id for d in tvt_diffs}:
        required_compliance[r] = False

    # Overall verdict logic
    if blocker_fail or any(not v for v in required_compliance.values()):
        overall = "FAIL"
    elif tcf.lab.verdict in {"BLOCKED", "PENDING"}:
        overall = tcf.lab.verdict
    elif any_fail:
        overall = "PASS-WITH-WARNINGS"
    else:
        overall = "PASS"

    overrides = _detect_silent_overrides(tcf)
    step_verdicts = _compute_step_verdicts(tcf, tvt_diffs)

    return TcfDiffResult(
        change_id=tcf.change_id,
        lab_verdict=tcf.lab.verdict,
        overall_verdict=overall,
        tvt_diffs=tvt_diffs,
        required_test_compliance=required_compliance,
        silent_overrides=overrides,
        step_verdicts=step_verdicts,
    )


__all__ = [
    "tcf_diff_spec_vs_lab",
    "TcfDiffResult",
    "TvtDiff",
    "SilentOverride",
    "StepVerdict",
]

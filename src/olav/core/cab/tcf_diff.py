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
from typing import Any

from .tcf_schema import CabTcf


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

        if not self.tvt_diffs and not self.silent_overrides:
            lines.append("(no TVT rows or overrides recorded)")
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

    return TcfDiffResult(
        change_id=tcf.change_id,
        lab_verdict=tcf.lab.verdict,
        overall_verdict=overall,
        tvt_diffs=tvt_diffs,
        required_test_compliance=required_compliance,
        silent_overrides=overrides,
    )


__all__ = [
    "tcf_diff_spec_vs_lab",
    "TcfDiffResult",
    "TvtDiff",
    "SilentOverride",
]

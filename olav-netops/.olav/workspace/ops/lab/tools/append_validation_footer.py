"""append_validation_footer — F3 lab→spec feedback channel.

After ops-lab finishes a CAB validation, this tool appends a
``## 🤖 Lab Validation Footer`` block to the original spec file.
Spec content stays intact; the footer documents the lab verdict +
diagnosis + recommendation in the same file the next reader (human
or agent) will open.

Without F3 the lab's high-quality FAIL diagnosis only persists for
the current session — independent ``cab_*_report.md`` files never
get linked back to the spec, so future readers don't know the spec
was validated, failed, or why.

See ``dev_docs/63 § F3`` and ``dev_docs/00 § ISSUE-LAB-NO-SPEC-FEEDBACK``.

Currently scope: PASS or FAIL footers; multiple footers append (audit
trail). Implementation is a thin file-append; no new schema, no new
infrastructure.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
while _PROJECT_ROOT.parent != _PROJECT_ROOT and not (_PROJECT_ROOT / "pyproject.toml").exists():
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


from langchain_core.tools import tool


_VALID_DECISIONS = {"PASS", "FAIL", "BLOCKED"}


@tool
def append_validation_footer(
    spec_path: str,
    decision: str,
    lab_name: str,
    snapshot_id: str = "",
    evidence: list[str] | None = None,
    recommendation: list[str] | None = None,
    full_report_path: str = "",
) -> str:
    """Append a Lab Validation Footer to a CAB spec file.

    Call this AFTER ``format_and_export`` writes the standalone lab
    report and BEFORE ``destroy_lab``. The footer carries the lab's
    verdict + diagnosis + recommendation back to the spec file so
    the next reader has a single self-contained artifact.

    Args:
        spec_path: Absolute path to the CAB spec file the lab
            validated. Footer is appended in-place; original content
            preserved. If the file doesn't exist the tool errors —
            check the spec was actually given as input to the lab.
        decision: ``"PASS"`` / ``"FAIL"`` / ``"BLOCKED"``.
        lab_name: The CLAB lab name (e.g. ``"cab_r1r4_ch4_v3"``).
        snapshot_id: Optional netops snapshot used for topology
            (e.g. ``"2026-03-30_2210"``).
        evidence: List of bullet-point evidence strings.
            For FAIL: include the specific failures the agent
            observed (e.g. ``["BGP r1 active (TCP fail)", "ARP empty
            on r1 e1-1"]``).
            For PASS: include verification facts (e.g. ``["BGP r1
            established with peer 172.16.99.2", "1 route exchanged
            each direction"]``).
        recommendation: List of next-step strings for the spec author
            (sim or human). For FAIL: what to fix in the next spec
            revision. For PASS: optional deployment notes.
        full_report_path: Optional path to the standalone lab report
            file (typical ``"exports/reports/cab_<lab>_report.md"``).
            Linked from the footer for full evidence.

    Returns:
        JSON string ``{"status": "ok", "appended_to": "<spec_path>",
        "footer_size": <chars>}`` on success, or ``{"status": "error",
        "error": "..."}`` on failure.

    Example:
        >>> append_validation_footer(
        ...     spec_path="/exports/reports/cab_r1_r4_ebgp_ch4.md",
        ...     decision="FAIL",
        ...     lab_name="cab_r1r4_ch4_ch5",
        ...     snapshot_id="2026-03-30_2210",
        ...     evidence=[
        ...         "BGP r1 active (TCP fail to 172.16.99.2)",
        ...         "Peer-AS mismatch: R1 local-as 65000 vs R4 peer-as 65999",
        ...     ],
        ...     recommendation=[
        ...         "Fix R4 peer-as: should be 65000 (matches R1 local-as)",
        ...         "Re-validate after sim revises the spec",
        ...     ],
        ...     full_report_path="exports/reports/cab_r1r4_ch4_ch5_report.md",
        ... )
    """
    p = Path(spec_path)
    if not p.exists():
        return json.dumps({
            "status": "error",
            "error": f"spec file not found: {spec_path}",
        })
    if not p.is_file():
        return json.dumps({
            "status": "error",
            "error": f"spec_path is not a regular file: {spec_path}",
        })

    decision = decision.upper().strip()
    if decision not in _VALID_DECISIONS:
        return json.dumps({
            "status": "error",
            "error": (
                f"decision must be one of {sorted(_VALID_DECISIONS)}; "
                f"got {decision!r}"
            ),
        })

    icon = {"PASS": "✅", "FAIL": "❌", "BLOCKED": "⏸️"}[decision]

    # Build the footer
    lines: list[str] = []
    lines.append("")  # ensure blank line before separator
    lines.append("---")
    lines.append("")
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(
        f"## 🤖 Lab Validation Footer — appended by ops-lab on {timestamp}"
    )
    lines.append("")
    header_bits = [f"**Decision**: {icon} {decision}"]
    header_bits.append(f"**Lab**: `{lab_name}`")
    if snapshot_id:
        header_bits.append(f"**Snapshot**: `{snapshot_id}`")
    lines.append("  ".join(header_bits))
    lines.append("")

    if decision == "PASS":
        if evidence:
            lines.append("**Evidence**:")
            lines.append("")
            for e in evidence:
                lines.append(f"- {e}")
            lines.append("")
        if recommendation:
            lines.append("**Notes for deployment**:")
            lines.append("")
            for r in recommendation:
                lines.append(f"- {r}")
            lines.append("")
    else:
        # FAIL or BLOCKED — diagnosis + recommendation
        if evidence:
            lines.append(f"**Why this spec failed lab validation**:")
            lines.append("")
            for e in evidence:
                lines.append(f"- {e}")
            lines.append("")
        if recommendation:
            lines.append("**Recommendation for sim revision**:")
            lines.append("")
            for r in recommendation:
                lines.append(f"- {r}")
            lines.append("")

    if full_report_path:
        lines.append(f"**Full lab report**: `{full_report_path}`")
        lines.append("")

    footer = "\n".join(lines)

    # Append (preserve original content)
    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(footer)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"file append failed: {type(e).__name__}: {e}",
        })

    return json.dumps({
        "status": "ok",
        "appended_to": str(p),
        "decision": decision,
        "footer_size": len(footer),
    })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    args = json.loads(parsed.args_json)
    print(append_validation_footer.invoke(args))

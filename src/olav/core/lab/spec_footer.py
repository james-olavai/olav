"""Append a Lab Validation Footer to a CAB markdown spec file.

Per ADR-0007 (Python-first tool architecture). The R90 TCF flow
prefers ``olav.core.cab.tcf_record_lab_run`` for structured
write-back; this helper exists for legacy markdown specs that don't
have a TCF YAML counterpart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_VALID_DECISIONS = {"PASS", "FAIL", "BLOCKED"}


def append_validation_footer(
    spec_path: str | Path,
    *,
    decision: str,
    lab_name: str,
    snapshot_id: str = "",
    evidence: list[str] | None = None,
    recommendation: list[str] | None = None,
    full_report_path: str = "",
) -> dict[str, Any]:
    p = Path(spec_path)
    if not p.exists():
        return {"status": "error", "error": f"spec file not found: {spec_path}"}
    if not p.is_file():
        return {"status": "error", "error": f"spec_path is not a regular file: {spec_path}"}

    decision = decision.upper().strip()
    if decision not in _VALID_DECISIONS:
        return {
            "status": "error",
            "error": (
                f"decision must be one of {sorted(_VALID_DECISIONS)}; "
                f"got {decision!r}"
            ),
        }

    icon = {"PASS": "✅", "FAIL": "❌", "BLOCKED": "⏸️"}[decision]

    lines: list[str] = ["", "---", ""]
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"## 🤖 Lab Validation Footer — appended by ops-lab on {timestamp}")
    lines.append("")
    header_bits = [f"**Decision**: {icon} {decision}", f"**Lab**: `{lab_name}`"]
    if snapshot_id:
        header_bits.append(f"**Snapshot**: `{snapshot_id}`")
    lines.append("  ".join(header_bits))
    lines.append("")

    if decision == "PASS":
        if evidence:
            lines.extend(["**Evidence**:", ""])
            lines.extend(f"- {e}" for e in evidence)
            lines.append("")
        if recommendation:
            lines.extend(["**Notes for deployment**:", ""])
            lines.extend(f"- {r}" for r in recommendation)
            lines.append("")
    else:
        if evidence:
            lines.extend(["**Why this spec failed lab validation**:", ""])
            lines.extend(f"- {e}" for e in evidence)
            lines.append("")
        if recommendation:
            lines.extend(["**Recommendation for sim revision**:", ""])
            lines.extend(f"- {r}" for r in recommendation)
            lines.append("")

    if full_report_path:
        lines.append(f"**Full lab report**: `{full_report_path}`")
        lines.append("")

    footer = "\n".join(lines)

    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(footer)
    except Exception as exc:
        return {
            "status": "error",
            "error": f"file append failed: {type(exc).__name__}: {exc}",
        }

    return {
        "status": "ok",
        "appended_to": str(p),
        "decision": decision,
        "footer_size": len(footer),
    }

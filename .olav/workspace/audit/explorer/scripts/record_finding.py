#!/usr/bin/env python3
"""Record one confirmed finding to netops.exploration_findings.

Anti-fabrication invariants enforced by the library:
  - evidence_sql must be non-empty (every finding needs a proof query)
  - severity must be: critical / high / medium / low / info
  - confidence must be: confirmed / hypothesis / refuted / not_applicable
  - phase must be: survey / hypothesise / test / correlate / report
  - duplicate summary within the same run_id is rejected

Args (JSON via stdin):
    run_id        str   — from start_exploration (required)
    phase         str   — survey/hypothesise/test/correlate/report (required)
    severity      str   — critical/high/medium/low/info (required)
    summary       str   — one-line finding description (required)
    evidence_sql  str   — the SQL query that proved this finding (required)
    confidence    str   — confirmed/hypothesis/refuted/not_applicable (default: confirmed)
    category      str   — optional label, e.g. "L1-interface" / "L3-routing"
    detail        str   — optional extended description
    evidence_rows list  — optional: rows from the evidence query (list of dicts)

Output JSON:
    finding_id  str  — opaque ID for this finding
    status      str  — "recorded"
"""
from __future__ import annotations

import json
import sys

from olav.core.config import MAIN_DB_PATH
from olav.core.explorer.scratchpad import record_finding


def main() -> None:
    raw = sys.stdin.read().strip()
    args: dict = json.loads(raw) if raw else {}

    run_id: str = args["run_id"]
    phase: str = args["phase"]
    severity: str = args["severity"]
    summary: str = args["summary"]
    evidence_sql: str = args["evidence_sql"]
    confidence: str = args.get("confidence") or "confirmed"
    category: str | None = args.get("category")
    detail: str | None = args.get("detail")
    evidence_rows: list | None = args.get("evidence_rows")

    finding_id = record_finding(
        db_path=MAIN_DB_PATH,
        run_id=run_id,
        phase=phase,
        severity=severity,
        summary=summary,
        evidence_sql=evidence_sql,
        confidence=confidence,
        category=category,
        detail=detail,
        evidence_rows=evidence_rows,
    )
    print(json.dumps({"finding_id": finding_id, "status": "recorded"}))


if __name__ == "__main__":
    main()

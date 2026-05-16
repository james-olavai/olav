"""@tool ``record_finding`` — write one audit finding to the scratchpad DB.

This is the LLM's "long-term memory" interface.  Strict input validation
in the underlying Python primitive (`olav.core.explorer.scratchpad`)
ensures every finding has SQL evidence and unique-per-run summary.
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def record_finding(
    run_id: str,
    phase: str,
    severity: str,
    summary: str,
    evidence_sql: str,
    confidence: str = "confirmed",
    category: str | None = None,
    detail: str | None = None,
    evidence_rows: list | None = None,
    related_findings: list | None = None,
) -> dict:
    """Record one finding to ``netops.exploration_findings``.

    Args:
        run_id:        From start_exploration().  All findings tagged with this.
        phase:         One of ``survey`` / ``hypothesise`` / ``test`` /
                       ``correlate`` / ``report`` — which workflow phase
                       produced this finding.
        severity:      ``critical`` / ``high`` / ``medium`` / ``low`` / ``info``.
        summary:       One-line headline.  MUST be unique within this run_id.
        evidence_sql:  The SQL query that proved this finding.  REQUIRED —
                       empty input is rejected (anti-fabrication invariant).
        confidence:    ``confirmed`` (default), ``hypothesis``, ``refuted``,
                       or ``not_applicable`` (when data isn't captured).
        category:      Free-form classification — LLM chooses (e.g.
                       "wireless_migration_drift", "vpc_consistency").
        detail:        Multi-paragraph explanation, root cause, recommendation.
        evidence_rows: Optional list of result rows from evidence_sql for repro.
        related_findings: List of other finding_ids this correlates with.

    Returns:
        ``{"finding_id": "<id>", "findings_so_far": <n>}`` on success.
        Raises ValueError on validation failure (empty evidence_sql,
        duplicate summary, budget exceeded, invalid severity/confidence).
    """
    from olav.core.config import MAIN_DB_PATH
    from olav.core.explorer.scratchpad import record_finding as _record
    import duckdb

    finding_id = _record(
        db_path=MAIN_DB_PATH,
        run_id=run_id, phase=phase,
        severity=severity, summary=summary,
        evidence_sql=evidence_sql,
        confidence=confidence,
        category=category, detail=detail,
        evidence_rows=evidence_rows,
        related_findings=related_findings,
    )
    # Tell the LLM how full its budget is now
    with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
        used = conn.execute(
            "SELECT findings_count, budget_findings FROM netops.exploration_runs "
            "WHERE run_id = ?", [run_id]
        ).fetchone()
    return {
        "finding_id": finding_id,
        "findings_used": used[0] if used else None,
        "findings_budget": used[1] if used else None,
    }

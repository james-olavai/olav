"""External scratchpad — DB-backed memory for the explorer sub-agent.

Three primitives, each with strict input validation.  See dev_docs/83
§4 for the full design contract.

Anti-fabrication invariants enforced HERE (in Python) AND at the DB
layer (NOT NULL + UNIQUE in v0_23 migration):

  1. ``evidence_sql`` cannot be empty / whitespace-only — every
     recorded finding must reference the query that proved it.
  2. ``severity`` must be one of ``critical / high / medium / low / info``.
  3. ``confidence`` must be one of
     ``confirmed / hypothesis / refuted / not_applicable``.
  4. Within a single ``run_id``, no duplicate ``summary`` — the LLM
     is forced to either merge into ``related_findings`` or rethink.
  5. ``record_finding`` rejects writes past ``budget_findings``.

These checks raise ``ValueError`` so the calling LLM sees a structured
error response (langchain serialises ValueErrors into tool-result
"error" channels).
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

# ── Enums ─────────────────────────────────────────────────────────────

_VALID_SEVERITY = frozenset({"critical", "high", "medium", "low", "info"})
_VALID_CONFIDENCE = frozenset({"confirmed", "hypothesis", "refuted", "not_applicable"})
_VALID_PHASE = frozenset({"survey", "hypothesise", "test", "correlate", "report"})
_VALID_STATUS = frozenset({"in_progress", "completed", "aborted", "timeout"})


def _now() -> datetime:
    return datetime.now(UTC)


def _short_id() -> str:
    return uuid.uuid4().hex[:16]


# ── start_exploration ─────────────────────────────────────────────────


def start_exploration(
    db_path: str | Path,
    *,
    snapshot_id: str,
    requested_by: str = "manual",
    budget_turns: int = 30,
    budget_findings: int = 20,
    budget_wall_sec: int = 1500,
) -> str:
    """Open a new exploration run; return its ``run_id``.

    Inserts an ``exploration_runs`` row with ``status='in_progress'`` and
    the provided budgets.  Future ``record_finding`` and
    ``update_exploration_run`` calls reference this ``run_id``.
    """
    run_id = "explore_" + _short_id()
    with duckdb.connect(str(db_path)) as conn:
        # Ensure the explorer tables exist on this DB (idempotent).
        from olav_netops.migrations.v0_23_exploration import apply_migration
        apply_migration(conn)

        conn.execute(
            """
            INSERT INTO netops.exploration_runs
              (run_id, started_at, status, snapshot_id, requested_by,
               budget_turns, budget_findings, budget_wall_sec,
               turns_used, findings_count, wall_sec_used)
            VALUES (?, ?, 'in_progress', ?, ?, ?, ?, ?, 0, 0, 0)
            """,
            [run_id, _now(), snapshot_id, requested_by,
             budget_turns, budget_findings, budget_wall_sec],
        )
    return run_id


# ── record_finding ────────────────────────────────────────────────────


def record_finding(
    db_path: str | Path,
    *,
    run_id: str,
    phase: str,
    severity: str,
    summary: str,
    evidence_sql: str,
    confidence: str = "confirmed",
    category: str | None = None,
    detail: str | None = None,
    evidence_rows: list[dict] | None = None,
    related_findings: list[str] | None = None,
) -> str:
    """Record one finding to ``netops.exploration_findings``.

    Validates inputs against the anti-fabrication invariants and
    rejects when the run has hit its ``budget_findings`` cap.  Returns
    the new ``finding_id``.
    """
    # ── Input validation (raise ValueError on contract violation) ──
    if not evidence_sql or not evidence_sql.strip():
        raise ValueError(
            "evidence_sql is required — every finding must include the "
            "SQL query that proved it (anti-fabrication invariant)."
        )
    if severity not in _VALID_SEVERITY:
        raise ValueError(
            f"severity must be one of {sorted(_VALID_SEVERITY)} — got {severity!r}"
        )
    if confidence not in _VALID_CONFIDENCE:
        raise ValueError(
            f"confidence must be one of {sorted(_VALID_CONFIDENCE)} — got {confidence!r}"
        )
    if phase not in _VALID_PHASE:
        raise ValueError(
            f"phase must be one of {sorted(_VALID_PHASE)} — got {phase!r}"
        )
    if not summary or not summary.strip():
        raise ValueError("summary cannot be empty")

    finding_id = "finding_" + _short_id()
    rows_json = json.dumps(evidence_rows) if evidence_rows else None
    related_json = json.dumps(related_findings) if related_findings else None

    with duckdb.connect(str(db_path)) as conn:
        # Budget check
        budget = conn.execute(
            "SELECT budget_findings, findings_count "
            "FROM netops.exploration_runs WHERE run_id = ?",
            [run_id],
        ).fetchone()
        if budget is None:
            raise ValueError(f"unknown run_id {run_id!r} — call start_exploration() first")
        cap, used = budget
        if used >= cap:
            raise ValueError(
                f"budget exceeded: this run already has {used}/{cap} findings"
            )

        # Duplicate summary check (also enforced by UNIQUE constraint)
        existing = conn.execute(
            "SELECT finding_id FROM netops.exploration_findings "
            "WHERE run_id = ? AND summary = ?",
            [run_id, summary],
        ).fetchone()
        if existing:
            raise ValueError(
                f"duplicate summary {summary!r} already exists in run {run_id} "
                f"(finding_id={existing[0]}) — merge via related_findings or "
                "rephrase to capture a different angle."
            )

        conn.execute(
            """
            INSERT INTO netops.exploration_findings
              (finding_id, run_id, recorded_at, phase, category, severity,
               summary, detail, evidence_sql, evidence_rows, confidence,
               related_findings)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [finding_id, run_id, _now(), phase, category, severity,
             summary, detail, evidence_sql, rows_json, confidence,
             related_json],
        )

        # Bump findings_count on the run
        conn.execute(
            "UPDATE netops.exploration_runs SET findings_count = findings_count + 1 "
            "WHERE run_id = ?",
            [run_id],
        )

    return finding_id


# ── update_exploration_run ────────────────────────────────────────────


def update_exploration_run(
    db_path: str | Path,
    *,
    run_id: str,
    status: str | None = None,
    turns_used: int | None = None,
    wall_sec_used: int | None = None,
    final_report_path: str | None = None,
) -> None:
    """Patch fields on an ``exploration_runs`` row.

    Only provided fields are touched (all kwargs are optional).  When
    ``status`` transitions to a terminal value (``completed``,
    ``aborted``, ``timeout``), ``ended_at`` is set automatically.
    """
    if status is not None and status not in _VALID_STATUS:
        raise ValueError(
            f"status must be one of {sorted(_VALID_STATUS)} — got {status!r}"
        )

    set_clauses: list[str] = []
    params: list[Any] = []

    if status is not None:
        set_clauses.append("status = ?")
        params.append(status)
        if status in {"completed", "aborted", "timeout"}:
            set_clauses.append("ended_at = ?")
            params.append(_now())
    if turns_used is not None:
        set_clauses.append("turns_used = ?")
        params.append(turns_used)
    if wall_sec_used is not None:
        set_clauses.append("wall_sec_used = ?")
        params.append(wall_sec_used)
    if final_report_path is not None:
        set_clauses.append("final_report_path = ?")
        params.append(final_report_path)

    if not set_clauses:
        return  # nothing to update

    params.append(run_id)
    sql = (
        f"UPDATE netops.exploration_runs SET {', '.join(set_clauses)} "
        f"WHERE run_id = ?"
    )
    with duckdb.connect(str(db_path)) as conn:
        conn.execute(sql, params)

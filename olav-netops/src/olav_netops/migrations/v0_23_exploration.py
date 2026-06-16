"""Migration v0.23: explorer sub-agent scratchpad tables (dev_docs/78).

Adds two tables in the netops schema:

  * ``netops.exploration_runs``     — one row per /explore invocation
  * ``netops.exploration_findings`` — per-finding scratchpad (external memory)

The explorer sub-agent is a Level-2 autonomous network audit agent
(see dev_docs/78 §2): the LLM acts as a senior architect, picks its
own investigation directions, and writes findings to these tables.

DDL invariants enforced here (anti-fabrication):

  * ``exploration_findings.evidence_sql NOT NULL``      — every
    finding must include the SQL query that proved it
  * ``UNIQUE (run_id, summary)``                        — prevents the
    LLM from recording the same finding twice within a run

Idempotent — safe to run against fresh DBs and against DBs already at
v0.23+.  The corresponding ``ExplorationRunsTable`` and
``ExplorationFindingsTable`` classes in ``olav_netops.core.tables``
mean fresh DBs get the schema via the standard ``ensure_schema()``
path; this migration covers the in-place ALTER + CREATE on existing
prod DBs.
"""
from __future__ import annotations


def apply_migration(conn) -> None:
    """Idempotently create the explorer scratchpad tables."""
    conn.execute("CREATE SCHEMA IF NOT EXISTS netops")

    # ── exploration_runs ──────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS netops.exploration_runs (
            run_id            VARCHAR PRIMARY KEY,
            started_at        TIMESTAMP NOT NULL,
            ended_at          TIMESTAMP,
            status            VARCHAR NOT NULL,
            snapshot_id       VARCHAR,
            requested_by      VARCHAR,
            budget_turns      INTEGER DEFAULT 30,
            budget_findings   INTEGER DEFAULT 20,
            budget_wall_sec   INTEGER DEFAULT 1500,
            turns_used        INTEGER DEFAULT 0,
            findings_count    INTEGER DEFAULT 0,
            wall_sec_used     INTEGER DEFAULT 0,
            final_report_path VARCHAR
        )
    """)

    # ── exploration_findings ──────────────────────────────────────
    # evidence_sql NOT NULL is the anti-fabrication invariant.
    # UNIQUE (run_id, summary) prevents duplicate findings within a run.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS netops.exploration_findings (
            finding_id        VARCHAR PRIMARY KEY,
            run_id            VARCHAR NOT NULL,
            recorded_at       TIMESTAMP NOT NULL,
            phase             VARCHAR NOT NULL,
            category          VARCHAR,
            severity          VARCHAR NOT NULL,
            summary           VARCHAR NOT NULL,
            detail            TEXT,
            evidence_sql      TEXT    NOT NULL,
            evidence_rows     VARCHAR,
            confidence        VARCHAR NOT NULL,
            related_findings  JSON,
            UNIQUE (run_id, summary)
        )
    """)

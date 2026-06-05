"""P0 — explorer DDL migration contract.

Two new tables in netops schema:
  * netops.exploration_runs       — one row per /explore invocation
  * netops.exploration_findings   — per-finding scratchpad (LLM's external memory)

The migration must be idempotent (re-running on an already-migrated DB
is a no-op) and additive — never destructive against existing tables.
"""
from __future__ import annotations

import duckdb
import pytest


@pytest.fixture()
def empty_main_conn():
    """A fresh in-memory connection with the netops schema present but no
    explorer tables yet — simulates a pre-v0.23 prod DB."""
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA netops")
    yield conn
    conn.close()


def _cols_of(conn, qualified: str) -> dict[str, str]:
    schema, table = qualified.split(".", 1)
    rows = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ?",
        [schema, table],
    ).fetchall()
    return {name: dtype for name, dtype in rows}


def _table_exists(conn, qualified: str) -> bool:
    schema, table = qualified.split(".", 1)
    row = conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?",
        [schema, table],
    ).fetchone()
    return bool(row and row[0])


class TestExplorerRunsTable:
    def test_apply_migration_creates_table(self, empty_main_conn):
        from olav_netops.migrations.v0_23_exploration import apply_migration
        apply_migration(empty_main_conn)
        assert _table_exists(empty_main_conn, "netops.exploration_runs")

    def test_runs_columns(self, empty_main_conn):
        from olav_netops.migrations.v0_23_exploration import apply_migration
        apply_migration(empty_main_conn)
        cols = _cols_of(empty_main_conn, "netops.exploration_runs")
        for expected in (
            "run_id", "started_at", "ended_at", "status",
            "snapshot_id", "requested_by",
            "budget_turns", "budget_findings", "budget_wall_sec",
            "turns_used", "findings_count", "wall_sec_used",
            "final_report_path",
        ):
            assert expected in cols, (
                f"exploration_runs missing column {expected!r}; have {sorted(cols)}"
            )

    def test_idempotent(self, empty_main_conn):
        from olav_netops.migrations.v0_23_exploration import apply_migration
        apply_migration(empty_main_conn)
        apply_migration(empty_main_conn)  # second call must not raise
        assert _table_exists(empty_main_conn, "netops.exploration_runs")


class TestExplorationFindingsTable:
    def test_table_created(self, empty_main_conn):
        from olav_netops.migrations.v0_23_exploration import apply_migration
        apply_migration(empty_main_conn)
        assert _table_exists(empty_main_conn, "netops.exploration_findings")

    def test_findings_columns(self, empty_main_conn):
        from olav_netops.migrations.v0_23_exploration import apply_migration
        apply_migration(empty_main_conn)
        cols = _cols_of(empty_main_conn, "netops.exploration_findings")
        for expected in (
            "finding_id", "run_id", "recorded_at", "phase", "category",
            "severity", "summary", "detail", "evidence_sql",
            "evidence_rows", "confidence", "related_findings",
        ):
            assert expected in cols, (
                f"exploration_findings missing column {expected!r}; have {sorted(cols)}"
            )

    def test_evidence_sql_not_null_enforced(self, empty_main_conn):
        """Anti-fabrication invariant — record_finding writes must include SQL."""
        from olav_netops.migrations.v0_23_exploration import apply_migration
        apply_migration(empty_main_conn)
        with pytest.raises(duckdb.Error):
            empty_main_conn.execute(
                "INSERT INTO netops.exploration_findings "
                "(finding_id, run_id, recorded_at, phase, severity, summary, "
                " evidence_sql, confidence) "
                "VALUES (?, ?, current_timestamp, ?, ?, ?, NULL, ?)",
                ["f1", "r1", "test", "info", "fabricated", "confirmed"],
            )

    def test_unique_summary_per_run(self, empty_main_conn):
        """UNIQUE(run_id, summary) prevents duplicate findings within a run."""
        from olav_netops.migrations.v0_23_exploration import apply_migration
        apply_migration(empty_main_conn)
        empty_main_conn.execute(
            "INSERT INTO netops.exploration_findings "
            "(finding_id, run_id, recorded_at, phase, severity, summary, "
            " evidence_sql, confidence) "
            "VALUES (?, ?, current_timestamp, ?, ?, ?, ?, ?)",
            ["f1", "r1", "test", "info", "duplicate me",
             "SELECT 1", "confirmed"],
        )
        with pytest.raises(duckdb.Error):
            empty_main_conn.execute(
                "INSERT INTO netops.exploration_findings "
                "(finding_id, run_id, recorded_at, phase, severity, summary, "
                " evidence_sql, confidence) "
                "VALUES (?, ?, current_timestamp, ?, ?, ?, ?, ?)",
                ["f2", "r1", "test", "info", "duplicate me",
                 "SELECT 2", "confirmed"],
            )

    def test_same_summary_allowed_across_different_runs(self, empty_main_conn):
        """Different run_ids may record the same summary (re-audit)."""
        from olav_netops.migrations.v0_23_exploration import apply_migration
        apply_migration(empty_main_conn)
        empty_main_conn.execute(
            "INSERT INTO netops.exploration_findings "
            "(finding_id, run_id, recorded_at, phase, severity, summary, "
            " evidence_sql, confidence) "
            "VALUES (?, ?, current_timestamp, ?, ?, ?, ?, ?)",
            ["f1", "r1", "test", "info", "same finding",
             "SELECT 1", "confirmed"],
        )
        # Different run — must succeed
        empty_main_conn.execute(
            "INSERT INTO netops.exploration_findings "
            "(finding_id, run_id, recorded_at, phase, severity, summary, "
            " evidence_sql, confidence) "
            "VALUES (?, ?, current_timestamp, ?, ?, ?, ?, ?)",
            ["f2", "r2", "test", "info", "same finding",
             "SELECT 1", "confirmed"],
        )


class TestRegistration:
    """The two tables register through TableRegistry via tables.py just like
    the other netops tables (so fresh DBs get them via ensure_schema)."""

    def test_runs_table_class_loadable(self):
        from olav_netops.core.tables import ExplorationRunsTable
        assert ExplorationRunsTable.schema_name == "netops"
        assert ExplorationRunsTable.table_name == "exploration_runs"

    def test_findings_table_class_loadable(self):
        from olav_netops.core.tables import ExplorationFindingsTable
        assert ExplorationFindingsTable.schema_name == "netops"
        assert ExplorationFindingsTable.table_name == "exploration_findings"

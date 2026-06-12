"""P1 — record_finding + update_exploration_run + start_exploration tools.

Three pure-Python primitives that the explorer sub-agent uses as its
external memory.  Pinned semantics:

  * ``start_exploration(...)``  → creates exploration_runs row, returns run_id
  * ``record_finding(...)``     → validates schema + budget, writes finding
  * ``update_exploration_run`` → bumps turns_used / wall_sec_used / status
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest


@pytest.fixture()
def seeded_db(tmp_path):
    """Fresh DB with the explorer tables migrated in."""
    db = tmp_path / "main.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        from olav_netops.migrations.v0_23_exploration import apply_migration
        apply_migration(conn)
    return db


# ── start_exploration ─────────────────────────────────────────────────


class TestStartExploration:
    def test_returns_run_id_and_writes_row(self, seeded_db):
        from olav.core.explorer.scratchpad import start_exploration
        run_id = start_exploration(
            db_path=seeded_db,
            snapshot_id="snap_xyz",
            requested_by="test",
        )
        assert run_id and len(run_id) >= 8

        with duckdb.connect(str(seeded_db), read_only=True) as conn:
            row = conn.execute(
                "SELECT run_id, status, snapshot_id, requested_by, "
                "       budget_turns, budget_findings, budget_wall_sec "
                "FROM netops.exploration_runs WHERE run_id = ?",
                [run_id],
            ).fetchone()
        assert row is not None
        assert row[1] == "in_progress"
        assert row[2] == "snap_xyz"
        assert row[3] == "test"
        # Defaults from the migration: 30/20/1500
        assert row[4] == 30
        assert row[5] == 20
        assert row[6] == 1500

    def test_custom_budget_overrides(self, seeded_db):
        from olav.core.explorer.scratchpad import start_exploration
        run_id = start_exploration(
            db_path=seeded_db,
            snapshot_id="s1",
            budget_turns=10, budget_findings=5, budget_wall_sec=300,
        )
        with duckdb.connect(str(seeded_db), read_only=True) as conn:
            row = conn.execute(
                "SELECT budget_turns, budget_findings, budget_wall_sec "
                "FROM netops.exploration_runs WHERE run_id = ?",
                [run_id],
            ).fetchone()
        assert row == (10, 5, 300)


# ── record_finding ────────────────────────────────────────────────────


class TestRecordFinding:
    def test_happy_path_writes_finding(self, seeded_db):
        from olav.core.explorer.scratchpad import record_finding, start_exploration
        run_id = start_exploration(db_path=seeded_db, snapshot_id="s1")
        finding_id = record_finding(
            db_path=seeded_db,
            run_id=run_id,
            phase="test",
            category="inventory",
            severity="info",
            summary="43 devices have vendor=Unknown",
            detail="These are CDP-only neighbours that lack a show_version capture.",
            evidence_sql="SELECT COUNT(*) FROM netops.devices WHERE vendor='Unknown'",
            evidence_rows=[{"count_star()": 43}],
            confidence="confirmed",
        )
        assert finding_id

        with duckdb.connect(str(seeded_db), read_only=True) as conn:
            row = conn.execute(
                "SELECT phase, category, severity, summary, confidence "
                "FROM netops.exploration_findings WHERE finding_id = ?",
                [finding_id],
            ).fetchone()
        assert row == ("test", "inventory", "info",
                       "43 devices have vendor=Unknown", "confirmed")

    def test_rejects_empty_evidence_sql(self, seeded_db):
        """Anti-fabrication: every finding must have its proof query."""
        from olav.core.explorer.scratchpad import record_finding, start_exploration
        run_id = start_exploration(db_path=seeded_db, snapshot_id="s1")
        with pytest.raises(ValueError, match="evidence_sql"):
            record_finding(
                db_path=seeded_db, run_id=run_id,
                phase="test", severity="info", summary="suspicious thing",
                evidence_sql="",  # empty — must be rejected
                confidence="confirmed",
            )

    def test_rejects_duplicate_summary_within_run(self, seeded_db):
        from olav.core.explorer.scratchpad import record_finding, start_exploration
        run_id = start_exploration(db_path=seeded_db, snapshot_id="s1")
        record_finding(
            db_path=seeded_db, run_id=run_id,
            phase="test", severity="info", summary="same finding",
            evidence_sql="SELECT 1", confidence="confirmed",
        )
        with pytest.raises(ValueError, match="duplicate"):
            record_finding(
                db_path=seeded_db, run_id=run_id,
                phase="test", severity="info", summary="same finding",
                evidence_sql="SELECT 2", confidence="confirmed",
            )

    def test_rejects_when_budget_findings_exceeded(self, seeded_db):
        from olav.core.explorer.scratchpad import record_finding, start_exploration
        run_id = start_exploration(
            db_path=seeded_db, snapshot_id="s1",
            budget_findings=2,
        )
        record_finding(db_path=seeded_db, run_id=run_id, phase="test",
                       severity="info", summary="finding 1",
                       evidence_sql="SELECT 1", confidence="confirmed")
        record_finding(db_path=seeded_db, run_id=run_id, phase="test",
                       severity="info", summary="finding 2",
                       evidence_sql="SELECT 2", confidence="confirmed")
        # 3rd should hit budget cap
        with pytest.raises(ValueError, match="budget"):
            record_finding(db_path=seeded_db, run_id=run_id, phase="test",
                           severity="info", summary="finding 3",
                           evidence_sql="SELECT 3", confidence="confirmed")

    def test_not_applicable_confidence_recorded(self, seeded_db):
        """When data isn't captured (e.g. no BGP), record explicitly — don't fake."""
        from olav.core.explorer.scratchpad import record_finding, start_exploration
        run_id = start_exploration(db_path=seeded_db, snapshot_id="s1")
        fid = record_finding(
            db_path=seeded_db, run_id=run_id,
            phase="test", severity="info",
            summary="BGP audit not possible — no BGP commands in fleet",
            evidence_sql="SELECT COUNT(*) FROM netops.parsed_outputs "
                        "WHERE command LIKE 'show ip bgp%'",
            evidence_rows=[{"count_star()": 0}],
            confidence="not_applicable",
        )
        with duckdb.connect(str(seeded_db), read_only=True) as conn:
            conf = conn.execute(
                "SELECT confidence FROM netops.exploration_findings WHERE finding_id = ?",
                [fid],
            ).fetchone()[0]
        assert conf == "not_applicable"

    def test_increments_findings_count(self, seeded_db):
        from olav.core.explorer.scratchpad import record_finding, start_exploration
        run_id = start_exploration(db_path=seeded_db, snapshot_id="s1")
        for i in range(3):
            record_finding(
                db_path=seeded_db, run_id=run_id, phase="test",
                severity="info", summary=f"finding {i}",
                evidence_sql=f"SELECT {i}", confidence="confirmed",
            )
        with duckdb.connect(str(seeded_db), read_only=True) as conn:
            n = conn.execute(
                "SELECT findings_count FROM netops.exploration_runs WHERE run_id = ?",
                [run_id],
            ).fetchone()[0]
        assert n == 3

    def test_rejects_invalid_severity(self, seeded_db):
        from olav.core.explorer.scratchpad import record_finding, start_exploration
        run_id = start_exploration(db_path=seeded_db, snapshot_id="s1")
        with pytest.raises(ValueError, match="severity"):
            record_finding(
                db_path=seeded_db, run_id=run_id, phase="test",
                severity="apocalyptic",  # not in enum
                summary="end of world", evidence_sql="SELECT 1",
                confidence="confirmed",
            )

    def test_rejects_invalid_confidence(self, seeded_db):
        from olav.core.explorer.scratchpad import record_finding, start_exploration
        run_id = start_exploration(db_path=seeded_db, snapshot_id="s1")
        with pytest.raises(ValueError, match="confidence"):
            record_finding(
                db_path=seeded_db, run_id=run_id, phase="test",
                severity="info", summary="weird",
                evidence_sql="SELECT 1",
                confidence="maybe",  # not in enum
            )


# ── update_exploration_run ────────────────────────────────────────────


class TestUpdateExplorationRun:
    def test_marks_run_completed(self, seeded_db):
        from olav.core.explorer.scratchpad import (
            start_exploration, update_exploration_run,
        )
        run_id = start_exploration(db_path=seeded_db, snapshot_id="s1")
        update_exploration_run(
            db_path=seeded_db, run_id=run_id,
            status="completed", turns_used=20, wall_sec_used=900,
            final_report_path="exports/reports/explore_test.md",
        )
        with duckdb.connect(str(seeded_db), read_only=True) as conn:
            row = conn.execute(
                "SELECT status, turns_used, wall_sec_used, final_report_path, "
                "       ended_at IS NOT NULL "
                "FROM netops.exploration_runs WHERE run_id = ?",
                [run_id],
            ).fetchone()
        assert row[0] == "completed"
        assert row[1] == 20
        assert row[2] == 900
        assert row[3] == "exports/reports/explore_test.md"
        assert row[4] is True  # ended_at populated

    def test_rejects_invalid_status(self, seeded_db):
        from olav.core.explorer.scratchpad import (
            start_exploration, update_exploration_run,
        )
        run_id = start_exploration(db_path=seeded_db, snapshot_id="s1")
        with pytest.raises(ValueError, match="status"):
            update_exploration_run(
                db_path=seeded_db, run_id=run_id, status="exploding",
            )

    def test_partial_update_only_touches_provided_fields(self, seeded_db):
        from olav.core.explorer.scratchpad import (
            start_exploration, update_exploration_run,
        )
        run_id = start_exploration(db_path=seeded_db, snapshot_id="s1")
        # Bump turns only — status / wall_sec stay at defaults
        update_exploration_run(db_path=seeded_db, run_id=run_id, turns_used=5)
        with duckdb.connect(str(seeded_db), read_only=True) as conn:
            row = conn.execute(
                "SELECT status, turns_used, wall_sec_used "
                "FROM netops.exploration_runs WHERE run_id = ?", [run_id],
            ).fetchone()
        assert row == ("in_progress", 5, 0)

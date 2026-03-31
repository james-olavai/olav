"""Phase 3-1 TDD: AuditEventRecorder — DuckDB-backed audit event storage.

Schema: audit_runs, audit_events, audit_tool_calls, audit_messages
"""
from __future__ import annotations

import uuid
from pathlib import Path


def test_audit_recorder_importable():
    from olav.core.audit_recorder import AuditEventRecorder  # noqa: F401


def test_audit_recorder_creates_tables(tmp_path):
    """On init, AuditEventRecorder must create the required DuckDB tables."""
    from olav.core.audit_recorder import AuditEventRecorder

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)
    recorder.close()

    import duckdb
    conn = duckdb.connect(str(db))
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    conn.close()

    assert "audit_runs" in tables
    assert "audit_events" in tables


def test_record_event_inserts_row(tmp_path):
    """recorder.record() must insert a row into audit_events."""
    from olav.core.audit_recorder import AuditEventRecorder

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)

    run_id = str(uuid.uuid4())
    recorder.record(
        event_type="user_input_received",
        run_id=run_id,
        payload={"content": "show bgp summary"},
    )
    recorder.close()

    import duckdb
    conn = duckdb.connect(str(db))
    rows = conn.execute(
        "SELECT event_type, run_id FROM audit_events WHERE run_id = ?", [run_id]
    ).fetchall()
    conn.close()

    assert len(rows) == 1, f"Expected 1 audit event row, got {len(rows)}"
    assert rows[0][0] == "user_input_received"
    assert rows[0][1] == run_id


def test_record_run_start_inserts_row(tmp_path):
    """recorder.record_run_start() must insert a row into audit_runs."""
    from olav.core.audit_recorder import AuditEventRecorder

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)

    run_id = str(uuid.uuid4())
    recorder.record_run_start(run_id=run_id, agent_id="ops", user_id="test_user")
    recorder.close()

    import duckdb
    conn = duckdb.connect(str(db))
    rows = conn.execute(
        "SELECT run_id, agent_id, user_id FROM audit_runs WHERE run_id = ?", [run_id]
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0][0] == run_id
    assert rows[0][1] == "ops"
    assert rows[0][2] == "test_user"


def test_record_run_end_updates_row(tmp_path):
    """recorder.record_run_end() must set status on the audit_runs row."""
    from olav.core.audit_recorder import AuditEventRecorder

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)

    run_id = str(uuid.uuid4())
    recorder.record_run_start(run_id=run_id, agent_id="ops", user_id="test_user")
    recorder.record_run_end(run_id=run_id, status="completed")
    recorder.close()

    import duckdb
    conn = duckdb.connect(str(db))
    rows = conn.execute(
        "SELECT status FROM audit_runs WHERE run_id = ?", [run_id]
    ).fetchall()
    conn.close()

    assert rows[0][0] == "completed"

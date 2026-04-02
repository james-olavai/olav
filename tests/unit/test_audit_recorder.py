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


def test_concurrent_writers_no_data_loss(tmp_path):
    """Multiple simultaneous AuditEventRecorder instances must ALL write successfully.

    This is the regression test for the original bug where only the first
    process acquired the DuckDB exclusive lock; all others silently lost data.
    """
    import threading
    from olav.core.audit_recorder import AuditEventRecorder

    db = tmp_path / "audit.duckdb"
    N = 10  # concurrent writers
    errors: list[str] = []

    def write_one(i: int) -> None:
        try:
            r = AuditEventRecorder(db_path=db)
            run_id = str(uuid.uuid4())
            r.record_run_start(run_id=run_id, agent_id=f"agent-{i}", user_id=f"user-{i}")
            r.record(event_type="test_event", run_id=run_id, payload={"worker": i})
            r.record_run_end(run_id=run_id, status="completed")
            r.close()
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=write_one, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Exceptions in threads: {errors}"

    import duckdb
    with duckdb.connect(str(db)) as conn:
        run_count = conn.execute("SELECT COUNT(*) FROM audit_runs").fetchone()[0]
        event_count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]

    assert run_count == N, f"Expected {N} audit_runs rows, got {run_count} — data was lost"
    assert event_count == N, f"Expected {N} audit_events rows, got {event_count} — data was lost"

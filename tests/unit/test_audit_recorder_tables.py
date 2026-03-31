"""Gap-B TDD: AuditEventRecorder must create all 4 required tables."""
from __future__ import annotations

import uuid
import json


def test_all_four_tables_exist(tmp_path):
    """audit_runs, audit_events, audit_tool_calls, audit_messages must all be created."""
    from olav.core.audit_recorder import AuditEventRecorder

    recorder = AuditEventRecorder(db_path=tmp_path / "audit.duckdb")
    recorder.close()

    import duckdb
    conn = duckdb.connect(str(tmp_path / "audit.duckdb"))
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    conn.close()

    assert "audit_runs" in tables
    assert "audit_events" in tables
    assert "audit_tool_calls" in tables, "audit_tool_calls table is missing"
    assert "audit_messages" in tables, "audit_messages table is missing"


def test_record_tool_call_inserts_row(tmp_path):
    """record_tool_call() must insert into audit_tool_calls."""
    from olav.core.audit_recorder import AuditEventRecorder

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)
    run_id = str(uuid.uuid4())
    recorder.record_tool_call(
        run_id=run_id,
        tool_name="show_interfaces",
        input_args={"device": "R1"},
        status="started",
    )
    recorder.close()

    import duckdb
    conn = duckdb.connect(str(db))
    rows = conn.execute(
        "SELECT tool_name, status FROM audit_tool_calls WHERE run_id = ?", [run_id]
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "show_interfaces"
    assert rows[0][1] == "started"


def test_record_message_inserts_row(tmp_path):
    """record_message() must insert into audit_messages."""
    from olav.core.audit_recorder import AuditEventRecorder

    db = tmp_path / "audit.duckdb"
    recorder = AuditEventRecorder(db_path=db)
    run_id = str(uuid.uuid4())
    recorder.record_message(
        run_id=run_id,
        role="assistant",
        content="Here is the BGP summary.",
    )
    recorder.close()

    import duckdb
    conn = duckdb.connect(str(db))
    rows = conn.execute(
        "SELECT role, content FROM audit_messages WHERE run_id = ?", [run_id]
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "assistant"
    assert rows[0][1] == "Here is the BGP summary."

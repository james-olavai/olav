"""TDD: ISSUE-M4-SESSION-SYNC-ACROSS-INTERFACES.

sessions table in audit.duckdb + AuditEventRecorder UPSERT.
"""

from __future__ import annotations

from pathlib import Path


def _make_recorder(db_path: Path):
    from olav.core.audit_recorder import AuditEventRecorder
    return AuditEventRecorder(db_path=str(db_path))


def test_sessions_table_created_on_migrate(tmp_path) -> None:
    """AuditEventRecorder should create the sessions table on first use."""
    import duckdb
    rec = _make_recorder(tmp_path / "audit.duckdb")

    with duckdb.connect(str(tmp_path / "audit.duckdb"), read_only=True) as conn:
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    assert "sessions" in tables, f"sessions table should exist, found: {tables}"


def test_record_run_start_upserts_session(tmp_path) -> None:
    """record_run_start() with thread_id should UPSERT into sessions."""
    import duckdb
    rec = _make_recorder(tmp_path / "audit.duckdb")

    rec.record_run_start(
        run_id="run-1",
        agent_id="core",
        thread_id="thread-abc",
        user_id="alice",
        source_channel="cli",
    )

    with duckdb.connect(str(tmp_path / "audit.duckdb"), read_only=True) as conn:
        rows = conn.execute(
            "SELECT thread_id, user_id, interface FROM sessions WHERE thread_id = 'thread-abc'"
        ).fetchall()
    assert len(rows) == 1, f"Expected 1 session row, got: {rows}"
    assert rows[0][1] == "alice"
    assert rows[0][2] == "cli"


def test_record_run_start_upsert_updates_existing(tmp_path) -> None:
    """Calling record_run_start twice with same thread_id should update, not insert duplicate."""
    import duckdb
    rec = _make_recorder(tmp_path / "audit.duckdb")

    rec.record_run_start(run_id="run-1", thread_id="thread-x", user_id="alice", source_channel="cli")
    rec.record_run_start(run_id="run-2", thread_id="thread-x", user_id="alice", source_channel="web")

    with duckdb.connect(str(tmp_path / "audit.duckdb"), read_only=True) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE thread_id = 'thread-x'"
        ).fetchone()
    assert rows[0] == 1, f"UPSERT should keep 1 row, not duplicate; found: {rows[0]}"


def test_record_run_start_without_thread_no_session(tmp_path) -> None:
    """record_run_start() without thread_id should NOT insert into sessions."""
    import duckdb
    rec = _make_recorder(tmp_path / "audit.duckdb")

    rec.record_run_start(run_id="run-no-thread", user_id="alice", source_channel="cli")

    with duckdb.connect(str(tmp_path / "audit.duckdb"), read_only=True) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert count == 0, f"No session row expected when thread_id is None; found: {count}"

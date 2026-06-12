"""Phase 4-4 TDD: `olav log` command family.

Tests:
  olav log               — list runs in last 24 hours
  olav log show <run_id> — full event sequence for a run
  olav log errors        — only error/failed events
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_recorder(db_path):
    from olav.core.audit_recorder import AuditEventRecorder
    return AuditEventRecorder(db_path=db_path)


def _seed_db(db_path):
    """Insert two runs: one recent (now), one old (48h ago)."""
    import duckdb

    r = _make_recorder(db_path)
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=48)

    # Recent run
    recent_id = str(uuid.uuid4())
    r.record_run_start(run_id=recent_id, agent_id="ops", user_id="alice")
    r.record("user_input_received", run_id=recent_id, payload={"content": "show bgp"})
    r.record_run_end(run_id=recent_id, status="completed")

    # Old run (force timestamp via direct SQL after inserting)
    old_id = str(uuid.uuid4())
    r.record_run_start(run_id=old_id, agent_id="ops", user_id="bob")
    r.close()

    # Backdate the old run's start_time
    conn = duckdb.connect(str(db_path))
    conn.execute(
        "UPDATE audit_runs SET start_time = ? WHERE run_id = ?",
        [old, old_id],
    )
    conn.execute(
        "UPDATE audit_events SET timestamp = ? WHERE run_id = ?",
        [old, old_id],
    )
    conn.close()

    return recent_id, old_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_log_list_importable():
    from olav.cli.log_cmd import log_list, log_show, log_errors  # noqa: F401


def test_log_list_returns_only_last_24h(tmp_path):
    """log_list() must return only runs from the last 24 hours."""
    from olav.cli.log_cmd import log_list

    db = tmp_path / "audit.duckdb"
    recent_id, old_id = _seed_db(db)

    rows = log_list(db_path=db)
    run_ids = [r["run_id"] for r in rows]

    assert recent_id in run_ids, "Recent run must appear in log_list"
    assert old_id not in run_ids, "Run older than 24h must be excluded from log_list"


def test_log_show_returns_full_event_sequence(tmp_path):
    """log_show(run_id) must return all events for that run in sequence_no order."""
    from olav.cli.log_cmd import log_show

    db = tmp_path / "audit.duckdb"
    recent_id, _ = _seed_db(db)

    events = log_show(run_id=recent_id, db_path=db)

    assert len(events) >= 1, "log_show must return at least one event"
    event_types = [e["event_type"] for e in events]
    assert "user_input_received" in event_types


def test_log_errors_filters_only_error_events(tmp_path):
    """log_errors() must return only events with error/failed event_type."""
    import duckdb
    from olav.cli.log_cmd import log_errors

    db = tmp_path / "audit.duckdb"
    r = _make_recorder(db)
    run_id = str(uuid.uuid4())
    r.record_run_start(run_id=run_id, agent_id="ops")
    r.record("tool_call_error", run_id=run_id, payload={"error": "timeout"})
    r.record("user_input_received", run_id=run_id, payload={"content": "test"})
    r.close()

    rows = log_errors(db_path=db)
    event_types = {r["event_type"] for r in rows}

    assert "tool_call_error" in event_types
    assert "user_input_received" not in event_types, (
        "log_errors must not include non-error events"
    )


def test_log_errors_since_param(tmp_path):
    """`log_errors(since_hours=2)` must only show errors from the last 2 hours."""
    import duckdb
    from olav.cli.log_cmd import log_errors

    db = tmp_path / "audit.duckdb"
    r = _make_recorder(db)
    run_id = str(uuid.uuid4())
    r.record_run_start(run_id=run_id, agent_id="ops")
    r.record("run_error", run_id=run_id, payload={"error": "crash"})
    r.close()

    # Backdate the error to 5 hours ago
    conn = duckdb.connect(str(db))
    conn.execute(
        "UPDATE audit_events SET timestamp = now() - INTERVAL 5 HOUR WHERE event_type = 'run_error'"
    )
    conn.close()

    rows = log_errors(db_path=db, since_hours=2)
    assert len(rows) == 0, "Errors older than since_hours window must be excluded"

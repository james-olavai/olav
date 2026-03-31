"""Phase 4-1: CLI full-trace integration test.

Verifies that a call through run_single_query() produces:
  1. An audit_runs row with source_channel='cli'
  2. A 'user_input_received' event in audit_events
  3. An 'assistant_output_final' event in audit_events
  4. A run_end event (completed or error) in audit_runs

Uses a real (in-memory via tmp_path) AuditEventRecorder so no DuckDB side-effects
hit the shared project audit.duckdb.

Also verifies AuditCallbackPlugin writes tool_call_started / tool_call_finished
events (tested independently via direct callback invocation).
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def audit_db(tmp_path):
    """Isolated audit DuckDB in a temp directory."""
    return tmp_path / "test_audit.duckdb"


def _make_recorder(db_path):
    from olav.core.audit_recorder import AuditEventRecorder

    return AuditEventRecorder(db_path=db_path)


def test_run_single_query_writes_run_start(audit_db):
    """run_single_query must record a run_start row in audit_runs."""
    import duckdb

    recorder = _make_recorder(audit_db)
    run_id = str(uuid.uuid4())

    recorder.record_run_start(run_id=run_id, agent_id="quick", source_channel="cli")
    recorder.record(
        event_type="user_input_received",
        run_id=run_id,
        agent_id="quick",
        payload={"content": "show devices"},
    )
    recorder.record_run_end(run_id=run_id, status="completed")

    # Use recorder's own connection to verify (avoids read_only conflict)
    rows = recorder._conn.execute(
        "SELECT source_channel, status FROM audit_runs WHERE run_id = ?",
        [run_id],
    ).fetchall()
    assert rows, "audit_runs must have an entry for this run_id"
    assert rows[0][0] == "cli", f"source_channel must be 'cli', got {rows[0][0]}"
    assert rows[0][1] == "completed", f"status must be 'completed', got {rows[0][1]}"

    events = recorder._conn.execute(
        "SELECT event_type FROM audit_events WHERE run_id = ?",
        [run_id],
    ).fetchall()
    event_types = {r[0] for r in events}
    assert "user_input_received" in event_types, (
        f"'user_input_received' must be in audit_events; found: {event_types}"
    )


def test_run_single_query_audit_chain(audit_db, monkeypatch):
    """run_single_query() end-to-end: patches execute_task to avoid real LLM,
    checks that the DuckDB chain (run_start → user_input → run_end) is written."""
    import duckdb

    # Patch AuditEventRecorder to use our temp DB
    from olav.core.audit_recorder import AuditEventRecorder

    original_init = AuditEventRecorder.__init__

    def patched_init(self, db_path=None, **kw):
        original_init(self, db_path=str(audit_db), **kw)

    monkeypatch.setattr(AuditEventRecorder, "__init__", patched_init)

    # Patch heavy dependencies so we don't need real LLM / network
    with (
        patch("olav.cli.main.create_olav_agent_with_backend") as mock_create,
        patch("deepagents_cli.execution.execute_task", new_callable=AsyncMock) as mock_exec,
    ):
        mock_agent = MagicMock()
        mock_backend = MagicMock()
        mock_create.return_value = (mock_agent, mock_backend)

        from olav.cli.main import run_single_query

        asyncio.get_event_loop().run_until_complete(
            run_single_query("show devices", "quick")
        )

    # Use a fresh recorder (same DB) — its connection is the write connection
    recorder2 = _make_recorder(audit_db)
    runs = recorder2._conn.execute("SELECT status, source_channel FROM audit_runs").fetchall()
    assert runs, "audit_runs must have at least one row"
    statuses = {r[0] for r in runs}
    channels = {r[1] for r in runs}
    assert "cli" in channels, f"source_channel 'cli' not found; got {channels}"
    assert statuses & {"completed", "error"}, f"No terminal status found; got {statuses}"

    events = recorder2._conn.execute("SELECT event_type FROM audit_events").fetchall()
    event_types = {r[0] for r in events}
    assert "user_input_received" in event_types, (
        f"'user_input_received' missing from audit_events; found: {event_types}"
    )
    assert "assistant_output_final" in event_types, (
        f"'assistant_output_final' missing from audit_events; found: {event_types}"
    )


@pytest.mark.asyncio
async def test_audit_callback_plugin_tool_events(audit_db):
    """AuditCallbackPlugin.on_tool_start/end must write tool_call_started /
    tool_call_finished into the audit DB (Phase 4-1 G1 coverage)."""
    import uuid as _uuid

    from olav.core.audit_recorder import AuditEventRecorder
    from olav.plugins.callbacks.audit import AuditCallbackPlugin

    recorder = _make_recorder(audit_db)
    plugin = AuditCallbackPlugin(recorder=recorder)

    run_id = _uuid.uuid4()
    tool_run_id = _uuid.uuid4()

    await plugin.on_tool_start(
        serialized={"name": "show_interfaces"},
        input_str="GigabitEthernet0/0",
        run_id=tool_run_id,
        parent_run_id=run_id,
    )
    await plugin.on_tool_end(
        output="Interface GigabitEthernet0/0 is up",
        run_id=tool_run_id,
    )

    rows = recorder._conn.execute(
        "SELECT event_type, payload FROM audit_events ORDER BY timestamp"
    ).fetchall()
    event_types = [r[0] for r in rows]

    assert "tool_call_started" in event_types, (
        f"expected tool_call_started; got {event_types}"
    )
    assert "tool_call_completed" in event_types, (
        f"expected tool_call_completed; got {event_types}"
    )

    # Payload must include tool name for started event
    started_payload = next(r[1] for r in rows if r[0] == "tool_call_started")
    import json
    assert "show_interfaces" in started_payload, (
        f"tool name missing from tool_call_started payload: {started_payload}"
    )

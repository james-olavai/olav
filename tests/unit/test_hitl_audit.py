"""Phase 4-2: HITL (Human-In-The-Loop) audit events test.

Verifies that when a HITL interrupt flow occurs, the audit DB receives:
  - A ``hitl_requested`` event with ``interrupt_id`` and ``action_requests``
  - A ``hitl_decision`` event with ``interrupt_id`` and ``decision``

The test mocks the interrupt itself — no real LLM or network access required.
The implementation under test is the ``_hitl_audit_scope`` context manager in
``src/olav/cli/main.py`` and the ``record_hitl_requested`` / ``record_hitl_decision``
convenience methods on ``AuditEventRecorder``.
"""
from __future__ import annotations

import json
import uuid
import duckdb
from pathlib import Path

import pytest


@pytest.fixture()
def audit_db(tmp_path: Path):
    """Isolated audit DuckDB in a temp directory."""
    return tmp_path / "hitl_audit.duckdb"


def _make_recorder(db_path: Path):
    from olav.core.audit_recorder import AuditEventRecorder

    return AuditEventRecorder(db_path=db_path)


# ---------------------------------------------------------------------------
# Unit tests for AuditEventRecorder HITL convenience methods
# ---------------------------------------------------------------------------


def test_record_hitl_requested_writes_event(audit_db: Path):
    """record_hitl_requested() must insert a hitl_requested row in audit_events."""
    recorder = _make_recorder(audit_db)
    run_id = str(uuid.uuid4())
    interrupt_id = str(uuid.uuid4())

    recorder.record_hitl_requested(
        run_id=run_id,
        interrupt_id=interrupt_id,
        action_requests=[{"name": "run_command", "description": "ping 8.8.8.8"}],
        agent_id="ops",
    )

    rows = duckdb.connect(str(recorder._db_path)).execute(
        "SELECT event_type, payload FROM audit_events WHERE run_id = ?",
        [run_id],
    ).fetchall()

    assert rows, "No audit_events row written"
    event_type, payload_str = rows[0]
    assert event_type == "hitl_requested", f"Expected hitl_requested, got {event_type}"

    payload = json.loads(payload_str)
    assert payload["interrupt_id"] == interrupt_id, f"interrupt_id mismatch: {payload}"
    assert "action_requests" in payload, f"action_requests missing: {payload}"


def test_record_hitl_decision_writes_event(audit_db: Path):
    """record_hitl_decision() must insert a hitl_decision row in audit_events."""
    recorder = _make_recorder(audit_db)
    run_id = str(uuid.uuid4())
    interrupt_id = str(uuid.uuid4())

    recorder.record_hitl_decision(
        run_id=run_id,
        interrupt_id=interrupt_id,
        decision="approve",
        agent_id="ops",
    )

    rows = duckdb.connect(str(recorder._db_path)).execute(
        "SELECT event_type, payload FROM audit_events WHERE run_id = ?",
        [run_id],
    ).fetchall()

    assert rows, "No audit_events row written"
    event_type, payload_str = rows[0]
    assert event_type == "hitl_decision", f"Expected hitl_decision, got {event_type}"

    payload = json.loads(payload_str)
    assert payload["interrupt_id"] == interrupt_id, f"interrupt_id mismatch: {payload}"
    assert payload["decision"] == "approve", f"decision mismatch: {payload}"


def test_record_hitl_reject_decision(audit_db: Path):
    """record_hitl_decision() must capture reject decisions."""
    recorder = _make_recorder(audit_db)
    run_id = str(uuid.uuid4())
    interrupt_id = str(uuid.uuid4())

    recorder.record_hitl_decision(
        run_id=run_id,
        interrupt_id=interrupt_id,
        decision="reject",
        agent_id="ops",
        auto_approve_enabled=False,
    )

    rows = duckdb.connect(str(recorder._db_path)).execute(
        "SELECT payload FROM audit_events WHERE run_id = ? AND event_type = 'hitl_decision'",
        [run_id],
    ).fetchall()
    assert rows
    payload = json.loads(rows[0][0])
    assert payload["decision"] == "reject"
    assert payload["auto_approve_enabled"] is False


# ---------------------------------------------------------------------------
# Integration test: _hitl_audit_scope patches prompt_for_tool_approval
# ---------------------------------------------------------------------------


def test_hitl_audit_scope_patches_prompt(audit_db: Path, monkeypatch):
    """_hitl_audit_scope injects audit events when prompt_for_tool_approval fires."""
    from olav.core.audit_recorder import AuditEventRecorder
    from olav.cli.main import _hitl_audit_scope
    import deepagents_cli.execution as _dce  # type: ignore[import]

    recorder = _make_recorder(audit_db)
    run_id = str(uuid.uuid4())

    # Replace the real interactive prompt with a non-blocking stub.
    monkeypatch.setattr(_dce, "prompt_for_tool_approval", lambda ar, ai: {"type": "approve"})

    with _hitl_audit_scope(recorder, run_id, "ops"):
        # Inside the scope the function should be the _audited wrapper.
        patched_fn = _dce.prompt_for_tool_approval
        result = patched_fn(
            {"name": "run_command", "description": "ping 8.8.8.8"},
            "ops",
        )
        assert result == {"type": "approve"}, "HITL decision should pass through"

    rows = duckdb.connect(str(recorder._db_path)).execute(
        "SELECT event_type FROM audit_events WHERE run_id = ? ORDER BY sequence_no",
        [run_id],
    ).fetchall()
    event_types = [r[0] for r in rows]

    assert "hitl_requested" in event_types, f"hitl_requested missing; got {event_types}"
    assert "hitl_decision" in event_types, f"hitl_decision missing; got {event_types}"

"""TDD tests for trace_learner.py skeleton (P3-1).

Verifies the core contract:
1. Reads recent error/cancelled runs from audit.duckdb
2. For each failed run, collects related tool_call_failed / run_error events
3. Returns a structured report (no LLM call in unit tests — that's integration)
4. The @tool wrapper is importable and callable
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest

_TOOL_PATH = Path("/home/yhvh/Olav/olav-netops/.olav/workspace/config/sync/tools/trace_learner.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_module():
    spec = importlib.util.spec_from_file_location("trace_learner", _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_recorder(db_path: Path):
    from olav.core.audit_recorder import AuditEventRecorder

    return AuditEventRecorder(db_path=db_path)


def _seed_failures(db_path: Path):
    """Insert 2 error runs and 1 completed run into audit.duckdb."""
    rec = _make_recorder(db_path)

    run_ok = str(uuid.uuid4())
    run_err1 = str(uuid.uuid4())
    run_err2 = str(uuid.uuid4())

    rec.record_run_start(
        run_id=run_ok, agent_id="ops", session_id="s1", thread_id="t1", user_id="alice"
    )
    rec.record(event_type="tool_call_started", run_id=run_ok, payload={"tool": "execute_cli"})
    rec.record(event_type="tool_call_completed", run_id=run_ok, payload={"tool": "execute_cli"})
    rec.record_run_end(run_id=run_ok, status="completed")

    rec.record_run_start(
        run_id=run_err1, agent_id="ops", session_id="s2", thread_id="t2", user_id="bob"
    )
    rec.record(event_type="tool_call_started", run_id=run_err1, payload={"tool": "execute_cli"})
    rec.record(
        event_type="tool_call_failed",
        run_id=run_err1,
        payload={"tool": "execute_cli", "error": "SSH timeout"},
    )
    rec.record_run_end(run_id=run_err1, status="error")

    rec.record_run_start(
        run_id=run_err2, agent_id="query", session_id="s3", thread_id="t3", user_id="alice"
    )
    rec.record(event_type="tool_call_started", run_id=run_err2, payload={"tool": "execute_sql"})
    rec.record(
        event_type="tool_call_failed",
        run_id=run_err2,
        payload={"tool": "execute_sql", "error": "table not found"},
    )
    rec.record(event_type="run_error", run_id=run_err2, payload={"error": "unhandled exception"})
    rec.record_run_end(run_id=run_err2, status="error")

    return run_ok, run_err1, run_err2


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_trace_learner_importable():
    """The file must exist and expose a trace_learner @tool (StructuredTool)."""
    mod = _load_module()
    assert hasattr(mod, "trace_learner"), "trace_learner tool not found"
    # LangChain @tool wraps into a StructuredTool; check it has an .invoke method
    assert hasattr(mod.trace_learner, "invoke"), "trace_learner has no .invoke — is it a @tool?"


def test_trace_learner_no_db_returns_error(tmp_path: Path):
    mod = _load_module()
    result = mod._analyze_failures(hours=24, limit=10, db_path=tmp_path / "missing.duckdb")
    assert result["status"] == "error"
    assert "not found" in result["message"].lower()


def test_trace_learner_counts_failures(tmp_path: Path):
    db_path = tmp_path / "audit.duckdb"
    _seed_failures(db_path)

    mod = _load_module()
    result = mod._analyze_failures(hours=48, limit=20, db_path=db_path)

    assert result["status"] == "success", result
    assert result["total_failures"] == 2, f"Expected 2 error runs: {result}"
    assert result["total_ok"] == 1, f"Expected 1 ok run: {result}"


def test_trace_learner_failure_details_contain_events(tmp_path: Path):
    db_path = tmp_path / "audit.duckdb"
    _seed_failures(db_path)

    mod = _load_module()
    result = mod._analyze_failures(hours=48, limit=20, db_path=db_path)

    assert result["status"] == "success"
    failures = result["failures"]
    assert len(failures) == 2

    # Each failure dict must have agent_id, run_id, and at least one error event
    for f in failures:
        assert "run_id" in f
        assert "agent_id" in f
        assert "error_events" in f
        assert len(f["error_events"]) >= 1, f"No error events for run {f['run_id']}"


def test_trace_learner_error_events_have_tool_and_error_fields(tmp_path: Path):
    db_path = tmp_path / "audit.duckdb"
    _seed_failures(db_path)

    mod = _load_module()
    result = mod._analyze_failures(hours=48, limit=20, db_path=db_path)

    all_events = [e for f in result["failures"] for e in f["error_events"]]
    tool_events = [e for e in all_events if e.get("event_type") == "tool_call_failed"]
    assert tool_events, "Expected at least one tool_call_failed event"
    for ev in tool_events:
        assert "tool" in ev or "error" in ev, f"Sparse event: {ev}"


def test_trace_learner_empty_db_returns_zero_failures(tmp_path: Path):
    """A fresh DB with no runs → success with zero failures."""
    db_path = tmp_path / "audit.duckdb"
    # Just initialise schema by making a recorder (no runs inserted)
    from olav.core.audit_recorder import AuditEventRecorder

    AuditEventRecorder(db_path=db_path)

    mod = _load_module()
    result = mod._analyze_failures(hours=24, limit=10, db_path=db_path)

    assert result["status"] == "success"
    assert result["total_failures"] == 0
    assert result["failures"] == []

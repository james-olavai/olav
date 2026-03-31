"""TDD tests for analyze_logs.py rewrite — queries audit.duckdb instead of
dead sources (llm_cache.sqlite / olav.json).

Phase: RED → verify tests fail before implementation, GREEN after rewrite.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_recorder(db_path: Path):
    from olav.core.audit_recorder import AuditEventRecorder
    return AuditEventRecorder(db_path=db_path)


def _seed_db(db_path: Path):
    """Insert representative audit data: 2 completed runs, 1 error run, tool calls."""
    from olav.core.audit_recorder import AuditEventRecorder

    rec = AuditEventRecorder(db_path=db_path)

    run1 = str(uuid.uuid4())
    run2 = str(uuid.uuid4())
    run_err = str(uuid.uuid4())

    rec.record_run_start(run_id=run1, agent_id="ops", session_id="s1", thread_id="t1", user_id="alice")
    rec.record(event_type="user_input_received", run_id=run1, payload={"text": "show interfaces"})
    rec.record(event_type="tool_call_started",   run_id=run1, payload={"tool": "execute_cli"})
    rec.record(event_type="tool_call_completed", run_id=run1, payload={"tool": "execute_cli"})
    rec.record(event_type="llm_usage",           run_id=run1, payload={"tokens_in": 100, "tokens_out": 50, "model": "claude-3-5-sonnet"})
    rec.record_run_end(run_id=run1, status="completed")

    rec.record_run_start(run_id=run2, agent_id="query", session_id="s2", thread_id="t2", user_id="bob")
    rec.record(event_type="user_input_received", run_id=run2, payload={"text": "what is bgp status"})
    rec.record(event_type="tool_call_started",   run_id=run2, payload={"tool": "execute_sql"})
    rec.record(event_type="tool_call_completed", run_id=run2, payload={"tool": "execute_sql"})
    rec.record(event_type="llm_usage",           run_id=run2, payload={"tokens_in": 80, "tokens_out": 40, "model": "claude-3-5-sonnet"})
    rec.record_run_end(run_id=run2, status="completed")

    rec.record_run_start(run_id=run_err, agent_id="ops", session_id="s3", thread_id="t3", user_id="alice")
    rec.record(event_type="user_input_received", run_id=run_err, payload={"text": "ping bad-host"})
    rec.record(event_type="tool_call_started",   run_id=run_err, payload={"tool": "execute_cli"})
    rec.record(event_type="tool_call_failed",    run_id=run_err, payload={"tool": "execute_cli", "error": "SSH timeout"})
    rec.record_run_end(run_id=run_err, status="error")

    return rec


# ---------------------------------------------------------------------------
# Import the implementation function (not the @tool wrapper)
# ---------------------------------------------------------------------------

_TOOL_PATH = Path("/home/yhvh/Olav/.olav/workspace/config/system/tools/analyze_logs.py")


def _get_impl():
    import importlib.util
    spec = importlib.util.spec_from_file_location("analyze_logs_tool", _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._analyze_audit_db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_analyze_logs_no_db_returns_error(tmp_path: Path):
    fn = _get_impl()
    result = fn(query="stats", hours=24, limit=10, keyword="", db_path=tmp_path / "missing.duckdb")
    assert result["status"] == "error"
    assert "not found" in result["message"].lower()


def test_analyze_logs_stats_returns_counts(tmp_path: Path):
    db_path = tmp_path / "audit.duckdb"
    _seed_db(db_path)

    fn = _get_impl()
    result = fn(query="stats", hours=48, limit=10, keyword="", db_path=db_path)

    assert result["status"] == "success", result
    assert result["total_runs"] == 3
    assert result["completed_runs"] == 2
    assert result["error_runs"] == 1


def test_analyze_logs_recent_returns_run_list(tmp_path: Path):
    db_path = tmp_path / "audit.duckdb"
    _seed_db(db_path)

    fn = _get_impl()
    result = fn(query="recent", hours=48, limit=5, keyword="", db_path=db_path)

    assert result["status"] == "success", result
    assert len(result["runs"]) == 3
    # Each entry should have agent_id and status
    for run in result["runs"]:
        assert "agent_id" in run
        assert "status" in run


def test_analyze_logs_errors_returns_only_failures(tmp_path: Path):
    db_path = tmp_path / "audit.duckdb"
    _seed_db(db_path)

    fn = _get_impl()
    result = fn(query="errors", hours=48, limit=10, keyword="", db_path=db_path)

    assert result["status"] == "success", result
    # Only error events: tool_call_failed and run_error
    for event in result["events"]:
        assert event["event_type"] in ("tool_call_failed", "run_error", "run_cancelled")


def test_analyze_logs_tool_usage_counts_tools(tmp_path: Path):
    db_path = tmp_path / "audit.duckdb"
    _seed_db(db_path)

    fn = _get_impl()
    result = fn(query="tool_usage", hours=48, limit=10, keyword="", db_path=db_path)

    assert result["status"] == "success", result
    tool_counts = {row["tool"]: row["count"] for row in result["tools"]}
    assert tool_counts.get("execute_cli", 0) == 2, f"execute_cli count wrong: {tool_counts}"
    assert tool_counts.get("execute_sql", 0) == 1, f"execute_sql count wrong: {tool_counts}"


def test_analyze_logs_models_sums_tokens(tmp_path: Path):
    db_path = tmp_path / "audit.duckdb"
    _seed_db(db_path)

    fn = _get_impl()
    result = fn(query="models", hours=48, limit=10, keyword="", db_path=db_path)

    assert result["status"] == "success", result
    model_row = next((r for r in result["models"] if "sonnet" in r["model"]), None)
    assert model_row is not None, f"claude model not found: {result}"
    assert model_row["tokens_in"] == 180   # 100 + 80
    assert model_row["tokens_out"] == 90   # 50 + 40


def test_analyze_logs_unknown_query_returns_error(tmp_path: Path):
    db_path = tmp_path / "audit.duckdb"
    _seed_db(db_path)

    fn = _get_impl()
    result = fn(query="banana", hours=24, limit=10, keyword="", db_path=db_path)

    assert result["status"] == "error"
    assert "unknown" in result["message"].lower()

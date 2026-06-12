from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import duckdb
import pytest

import importlib.util as _ilu
from pathlib import Path as _Path
_REPO = _Path(__file__).resolve().parents[2]
_spec = _ilu.spec_from_file_location(
    "analyze_logs_script",
    _REPO / ".olav" / "workspace" / "admin" / "ops" / "scripts" / "analyze_logs.py",
)
al = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(al)


def _seed_audit_db(db_path):
    now = datetime.now(timezone.utc)
    run_start = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    evt_ts = (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

    with duckdb.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE audit_runs (
                run_id VARCHAR,
                agent_id VARCHAR,
                status VARCHAR,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                user_id VARCHAR
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE audit_events (
                event_type VARCHAR,
                timestamp TIMESTAMP,
                agent_id VARCHAR,
                payload VARCHAR
            )
            """
        )
        conn.execute(
            "INSERT INTO audit_runs VALUES "
            "('r1', 'agent-a', 'completed', ?, ?, 'u1'),"
            "('r2', 'agent-b', 'error', ?, ?, 'u2'),"
            "('r3', 'agent-c', 'cancelled', ?, NULL, 'u3')",
            [run_start, run_start, run_start, run_start, run_start],
        )
        conn.execute(
            "INSERT INTO audit_events VALUES "
            "('tool_call_failed', ?, 'agent-b', ?),"
            "('tool_call_started', ?, 'agent-a', ?),"
            "('llm_usage', ?, 'agent-a', ?)",
            [
                evt_ts,
                json.dumps({"error": "timeout"}),
                evt_ts,
                json.dumps({"tool": "workspace_health"}),
                evt_ts,
                json.dumps({"model": "gpt-5-mini", "tokens_in": "10", "tokens_out": "20"}),
            ],
        )


def test_analyze_audit_db_returns_error_when_db_missing(tmp_path):
    out = al._analyze_audit_db(db_path=tmp_path / "missing.duckdb")
    assert out["status"] == "error"
    assert "not found" in out["message"]


def test_analyze_audit_db_open_failure(monkeypatch, tmp_path):
    db = tmp_path / "audit.duckdb"
    db.write_text("stub", encoding="utf-8")

    def _boom(*_args, **_kwargs):
        raise OSError("open failed")

    monkeypatch.setattr(al.duckdb, "connect", _boom)
    out = al._analyze_audit_db(db_path=db)
    assert out["status"] == "error"
    assert "Cannot open audit.duckdb" in out["message"]


def test_analyze_audit_db_unknown_query(tmp_path):
    db = tmp_path / "audit.duckdb"
    _seed_audit_db(db)
    out = al._analyze_audit_db(query="what_is_this", db_path=db)
    assert out["status"] == "error"
    assert "unknown query type" in out["message"]


def test_analyze_audit_db_stats_recent_errors_tool_usage_models(tmp_path):
    db = tmp_path / "audit.duckdb"
    _seed_audit_db(db)

    stats = al._analyze_audit_db(query="stats", hours=24, db_path=db)
    assert stats["status"] == "success"
    assert stats["total_runs"] == 3
    assert stats["completed_runs"] == 1
    assert stats["error_runs"] == 1
    assert stats["cancelled_runs"] == 1

    recent = al._analyze_audit_db(query="recent", hours=24, limit=5, db_path=db)
    assert recent["status"] == "success"
    assert len(recent["runs"]) == 3
    assert all("run_id" in r for r in recent["runs"])

    errors = al._analyze_audit_db(query="errors", hours=24, limit=5, db_path=db)
    assert errors["status"] == "success"
    assert len(errors["events"]) == 1
    assert errors["events"][0]["event_type"] == "tool_call_failed"
    assert errors["events"][0]["error"] == "timeout"

    tools = al._analyze_audit_db(query="tool_usage", hours=24, limit=5, db_path=db)
    assert tools["status"] == "success"
    assert tools["tools"] == [{"tool": "workspace_health", "count": 1}]

    models = al._analyze_audit_db(query="models", hours=24, limit=5, db_path=db)
    assert models["status"] == "success"
    assert models["models"] == [
        {"model": "gpt-5-mini", "tokens_in": 10, "tokens_out": 20, "calls": 1}
    ]


def test_analyze_logs_tool_entrypoint(monkeypatch):
    def _fake_impl(query, hours, limit, keyword):
        return {"status": "success", "query": query, "hours": hours, "limit": limit, "keyword": keyword}

    monkeypatch.setattr(al, "_analyze_audit_db", _fake_impl)
    if hasattr(al.analyze_logs, "invoke"):
        out = al.analyze_logs.invoke({"query": "stats", "hours": 6, "limit": 7, "keyword": "k"})
    else:
        out = al.analyze_logs(query="stats", hours=6, limit=7, keyword="k")
    assert out == {"status": "success", "query": "stats", "hours": 6, "limit": 7, "keyword": "k"}

"""Unit tests for admin/ops/tools — direct tool implementations.

v0.11.0: The importlib wrapper pattern (admin/ops → core/admin) was dissolved.
post-R-AGENT-HIERARCHY: manage_service removed from admin/ops (Direction A);
service lifecycle is now devops/services authority. See devops/services/tools/.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
OPS_TOOLS = REPO / ".olav" / "workspace" / "admin" / "ops" / "scripts"


def _load(name: str):
    path = OPS_TOOLS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_test_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_analyze_logs_is_tool():
    mod = _load("analyze_logs")
    assert callable(mod.analyze_logs), "analyze_logs must be callable"
    assert hasattr(mod, "_analyze_audit_db"), "analyze_logs must expose _analyze_audit_db for testability"


def test_analyze_logs_unknown_query(tmp_path):
    import duckdb
    db = tmp_path / "audit.duckdb"
    conn = duckdb.connect(str(db))
    conn.execute("CREATE TABLE audit_runs (run_id VARCHAR, agent_id VARCHAR, status VARCHAR, start_time TIMESTAMP, end_time TIMESTAMP, user_id VARCHAR)")
    conn.close()

    mod = _load("analyze_logs")
    result = mod._analyze_audit_db(query="unknown_mode", db_path=db)
    assert result["status"] == "error"
    assert "unknown query type" in result["message"]


def test_analyze_logs_stats_on_empty_db(tmp_path):
    import duckdb
    db = tmp_path / "audit.duckdb"
    conn = duckdb.connect(str(db))
    conn.execute("CREATE TABLE audit_runs (run_id VARCHAR, agent_id VARCHAR, status VARCHAR, start_time TIMESTAMP, end_time TIMESTAMP, user_id VARCHAR)")
    conn.close()

    mod = _load("analyze_logs")
    result = mod._analyze_audit_db(query="stats", db_path=db)
    assert result["status"] == "success"
    assert result["total_runs"] == 0


def test_bulk_ingest_is_tool():
    mod = _load("bulk_ingest")
    assert callable(mod.bulk_ingest), "bulk_ingest must be callable"



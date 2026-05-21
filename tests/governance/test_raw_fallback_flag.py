"""RAW-05 M: ``raw_fallback: true`` surfaces raw-only data from audit jobs.

When a profile job's primary query returns zero rows but
``netops.raw_output_store`` still holds captures for the same command
pattern, ``_raw_fallback_probe`` emits ``_warning: raw_only_data``
sentinels. That turns a silent "looks healthy" outcome into a visible
"data couldn't actually be analysed" signal.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import duckdb
import pytest


REPO = Path(__file__).resolve().parents[2]
MAP_ENGINE_PY = REPO / ".olav" / "workspace" / "audit" / "audit-runner" / "scripts" / "map_engine.py"


@pytest.fixture
def map_engine():
    assert MAP_ENGINE_PY.exists(), f"map_engine.py missing at {MAP_ENGINE_PY}"
    spec = importlib.util.spec_from_file_location("map_engine_for_test", MAP_ENGINE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def conn():
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE SCHEMA netops")
    conn.execute(
        """
        CREATE TABLE netops.raw_output_store (
            device_name VARCHAR, command VARCHAR,
            raw_output TEXT, snapshot_id VARCHAR
        )
        """
    )
    yield conn
    conn.close()


def test_probe_no_ilike_in_query_is_noop(map_engine, conn):
    # Query doesn't reference command ILIKE — probe can't extract a pattern
    # and must not explode or emit anything.
    result = map_engine._raw_fallback_probe(
        conn,
        "SELECT device_name FROM parsed_outputs WHERE snapshot_id = 'x'",
    )
    assert result == []


def test_probe_surfaces_raw_only_rows(map_engine, conn):
    conn.execute(
        "INSERT INTO netops.raw_output_store VALUES "
        "('R1', 'show processes cpu', 'CPU util for five seconds: 5%/0%', 'snap_A'),"
        "('R2', 'show processes cpu', 'CPU util for five seconds: 8%/0%', 'snap_A')"
    )
    query = """
        SELECT device_name FROM parsed_outputs
        WHERE command ILIKE '%processes cpu%' AND created_at >= $cutoff
    """
    result = map_engine._raw_fallback_probe(conn, query)

    assert len(result) == 2
    assert all(r["_warning"] == "raw_only_data" for r in result)
    devices = {r["device_name"] for r in result}
    assert devices == {"R1", "R2"}
    assert all(r["command"] == "show processes cpu" for r in result)


def test_probe_filters_empty_raw_output(map_engine, conn):
    conn.execute(
        "INSERT INTO netops.raw_output_store VALUES "
        "('R1', 'show processes cpu', '', 'snap_A'),"
        "('R2', 'show processes cpu', NULL, 'snap_A')"
    )
    query = "SELECT x FROM parsed_outputs WHERE command ILIKE '%processes cpu%'"
    result = map_engine._raw_fallback_probe(conn, query)
    assert result == []


def test_probe_respects_max_findings(map_engine, conn):
    for i in range(10):
        conn.execute(
            "INSERT INTO netops.raw_output_store VALUES "
            "(?, 'show processes cpu', 'data', 'snap_A')",
            [f"R{i}"],
        )
    query = "SELECT x FROM parsed_outputs WHERE command ILIKE '%processes cpu%'"
    result = map_engine._raw_fallback_probe(conn, query, max_findings=3)
    assert len(result) == 3


def test_probe_tolerates_missing_table(map_engine):
    # No netops.raw_output_store in this fresh connection — the probe logs
    # at debug and returns [] rather than raising.
    tmp = duckdb.connect(":memory:")
    try:
        query = "SELECT x FROM parsed_outputs WHERE command ILIKE '%cpu%'"
        assert map_engine._raw_fallback_probe(tmp, query) == []
    finally:
        tmp.close()


def test_profile_has_raw_fallback_flag_on_anomaly_jobs():
    """health_full_drift.md must mark both CPU and Memory anomaly jobs."""
    profile = (
        REPO / ".olav" / "workspace" / "audit" / "profiles" / "health_full_drift.md"
    ).read_text(encoding="utf-8")
    # Cheap structural check: two `raw_fallback: true` lines — one per job.
    assert profile.count("raw_fallback: true") >= 2, (
        "Expected at least 2 `raw_fallback: true` markers in health_full_drift.md "
        "(CPU_Anomaly + Memory_Anomaly). RAW-05 regression if they disappear."
    )

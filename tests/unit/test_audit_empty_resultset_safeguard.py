"""Tests for ISSUE-AUDIT-FALSE-GREEN-EMPTY-RESULTSET fix in
``olav-netops/.olav/workspace/audit/runner/tools/map_engine.py`` (path
moved from ``auditor/`` to ``runner/`` in rev 259's Run/Author split).

Verifies that when a SQL audit job returns no findings:
  * empty source table → synthetic Critical "Insufficient Data" finding
  * stale data outside window → synthetic Warning finding
  * legitimate "all healthy" with rows in source AND filters matched none
    is currently treated as window-too-narrow (operator decides).

Without this safeguard, audit silently reports "✅ Healthy" off any
empty resultset — masking dead schemas, broken collection, or stale
windows.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import duckdb
import pytest


# Load map_engine via spec since it lives in the workspace tools/, not on
# sys.path. Mirrors how the running agent loads it.
_ME_PATH = (
    Path("/home/yhvh/Olav/olav-netops/.olav/workspace/audit/runner/tools/map_engine.py")
)


@pytest.fixture(scope="module")
def map_engine():
    spec = importlib.util.spec_from_file_location("_test_map_engine", _ME_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_test_map_engine"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def db():
    con = duckdb.connect(":memory:")
    yield con
    con.close()


def test_extract_first_table_basic(map_engine):
    q = "SELECT * FROM bgp_neighbors WHERE state != 'Established'"
    assert map_engine._extract_first_table(q) == "bgp_neighbors"


def test_extract_first_table_with_schema(map_engine):
    q = "SELECT * FROM netops.v_bgp_neighbors_auto WHERE state IS NULL"
    assert map_engine._extract_first_table(q) == "netops.v_bgp_neighbors_auto"


def test_extract_first_table_returns_none_on_no_from(map_engine):
    assert map_engine._extract_first_table("SELECT 1") is None


def test_check_data_sufficiency_empty_source_critical(map_engine, db):
    """Empty table → Critical 'empty_source' finding."""
    db.execute("CREATE TABLE bgp_neighbors (device_name VARCHAR, state VARCHAR)")
    finding = map_engine._check_data_sufficiency(
        db, "SELECT * FROM bgp_neighbors WHERE state != 'Established'", "BGP_HEALTH"
    )
    assert finding is not None
    assert finding["severity_hint"] == "Critical"
    assert finding["_warning"] == "empty_source"
    assert finding["_source"]["table"] == "bgp_neighbors"
    assert finding["_source"]["row_count_total"] == 0
    assert "0 rows total" in finding["reason"]
    assert "BGP_HEALTH" in finding["reason"]


def test_check_data_sufficiency_stale_window_warning(map_engine, db):
    """Source has rows + query uses :window placeholder + 0 rows
    matched → Warning 'empty_window' finding."""
    db.execute("CREATE TABLE bgp_neighbors (device_name VARCHAR, state VARCHAR)")
    db.execute(
        "INSERT INTO bgp_neighbors VALUES ('R1', 'Established'), ('R2', 'Established')"
    )
    # Query MUST include :window to opt into the empty-window flag —
    # without it, 0 rows is a legitimate "all healthy" answer.
    finding = map_engine._check_data_sufficiency(
        db,
        "SELECT * FROM bgp_neighbors WHERE created_at >= NOW() - INTERVAL :window AND state != 'Established'",
        "BGP_HEALTH",
    )
    assert finding is not None
    assert finding["severity_hint"] == "Warning"
    assert finding["_warning"] == "empty_window"
    assert finding["_source"]["row_count_total"] == 2


def test_check_data_sufficiency_returns_none_when_no_table(map_engine, db):
    """Query without a FROM clause → can't evaluate sufficiency, return
    None (caller treats as legitimate 0 findings)."""
    assert map_engine._check_data_sufficiency(db, "SELECT 1", "BOGUS") is None


def test_check_data_sufficiency_returns_none_on_missing_table(map_engine, db):
    """Table doesn't exist → silent skip; never crash audit pipeline."""
    finding = map_engine._check_data_sufficiency(
        db, "SELECT * FROM nonexistent_table", "BGP_HEALTH"
    )
    # COUNT(*) on missing table raises; helper catches → None
    assert finding is None


def test_check_data_sufficiency_no_window_legitimate_empty(map_engine, db):
    """Query without :window placeholder + 0 rows = legitimate 'all
    healthy' signal. Should return None, not promote to warning.
    Regression for false-positive on OSPF_NON_FULL_NEIGHBORS audit."""
    db.execute("CREATE TABLE v_ospf_neighbors_auto (state VARCHAR)")
    db.execute("INSERT INTO v_ospf_neighbors_auto VALUES ('FULL'), ('Full')")
    # Query has no :window placeholder
    finding = map_engine._check_data_sufficiency(
        db,
        "SELECT * FROM v_ospf_neighbors_auto WHERE UPPER(state) NOT LIKE 'FULL%'",
        "OSPF_NON_FULL",
    )
    assert finding is None, (
        "0 rows + no :window should be legitimate healthy, not Insufficient Data"
    )


def test_check_data_sufficiency_finding_has_required_shape(map_engine, db):
    """Synthetic finding must have the keys downstream renderer needs."""
    db.execute("CREATE TABLE empty_t (x INT)")
    finding = map_engine._check_data_sufficiency(
        db, "SELECT * FROM empty_t WHERE x > 0", "T1"
    )
    for key in ("device", "metric_value", "metric_name", "severity_hint",
                "_warning", "_source", "reason"):
        assert key in finding, f"missing required key: {key}"
    assert finding["metric_name"] == "Insufficient Data"


# ── ISSUE-AUDIT-FINDINGS-CAP-SILENT-TRUNCATION (P1, 2026-05-12) ────────


def test_execute_sql_job_returns_tuple_with_total(map_engine, db):
    """_execute_sql_job MUST return (findings, total_count). Total
    equals len(findings) when not truncated."""
    db.execute("CREATE TABLE t (x INT)")
    db.execute("INSERT INTO t VALUES (1), (2), (3)")
    findings, total = map_engine._execute_sql_job(
        conn=db,
        query="SELECT x FROM t",
        window="1h",
        max_findings=10,
    )
    assert len(findings) == 3
    assert total == 3


def test_execute_sql_job_surfaces_truncation_total(map_engine, db):
    """When SQL produces > max_findings rows, return (truncated_findings,
    EXACT total). Without exact total the operator cannot tell whether
    they lost 5 findings or 5000."""
    db.execute("CREATE TABLE t (x INT)")
    db.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(100)])
    findings, total = map_engine._execute_sql_job(
        conn=db,
        query="SELECT x FROM t",
        window="1h",
        max_findings=10,
    )
    assert len(findings) == 10, "findings list must be capped at max_findings"
    assert total == 100, (
        "truncation must surface the EXACT total row count; "
        "without it the operator cannot judge severity of the cut"
    )


def test_execute_sql_job_no_truncation_at_exact_cap(map_engine, db):
    """Findings exactly at max_findings → no truncation flag (total == len).
    Tests the boundary condition: cap=5, rows=5 must NOT trigger truncation."""
    db.execute("CREATE TABLE t (x INT)")
    db.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(5)])
    findings, total = map_engine._execute_sql_job(
        conn=db,
        query="SELECT x FROM t",
        window="1h",
        max_findings=5,
    )
    assert len(findings) == 5
    assert total == 5, "boundary: exactly max_findings rows means no truncation"


# ── ISSUE-AUDIT-SCHEMA-DRIFT-NO-SELFTEST (P2, 2026-05-12) ──────────────


def test_selftest_profile_ok(map_engine, db, tmp_path):
    """All jobs reference valid tables/columns → ok=True."""
    db.execute("CREATE TABLE bgp_neighbors (device VARCHAR, state VARCHAR)")
    db.execute("INSERT INTO bgp_neighbors VALUES ('R1', 'Established')")
    profile = tmp_path / "ok_profile.md"
    profile.write_text(
        "---\n"
        "name: test_ok\n"
        "jobs:\n"
        "  - name: bgp_check\n"
        "    type: sql\n"
        "    severity: Warning\n"
        "    query: \"SELECT device, state FROM bgp_neighbors\"\n"
        "---\n# body\n"
    )
    # Patch MAIN_DB_PATH-equivalent by passing db_path explicitly. The
    # function expects a path string; spin up a temp file db.
    db_file = tmp_path / "t.duckdb"
    import duckdb as _d
    src = _d.connect(str(db_file))
    src.execute("CREATE TABLE bgp_neighbors (device VARCHAR, state VARCHAR)")
    src.execute("INSERT INTO bgp_neighbors VALUES ('R1', 'Established')")
    src.close()
    result = map_engine.selftest_profile(str(profile), db_path=str(db_file))
    assert result["ok"] is True
    assert result["profile"] == "test_ok"
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["status"] == "ok"
    assert result["jobs"][0]["error"] is None


def test_selftest_profile_missing_table(map_engine, tmp_path):
    """Job references a table that doesn't exist → schema_error."""
    profile = tmp_path / "bad_profile.md"
    profile.write_text(
        "---\n"
        "name: test_missing_table\n"
        "jobs:\n"
        "  - name: bgp_check\n"
        "    type: sql\n"
        "    severity: Warning\n"
        "    query: \"SELECT * FROM nonexistent_table\"\n"
        "---\n# body\n"
    )
    db_file = tmp_path / "t.duckdb"
    import duckdb as _d
    _d.connect(str(db_file)).close()  # create empty db
    result = map_engine.selftest_profile(str(profile), db_path=str(db_file))
    assert result["ok"] is False
    assert result["jobs"][0]["status"] == "schema_error"
    assert "nonexistent_table" in result["jobs"][0]["error"] or "Catalog" in result["jobs"][0]["error"]


def test_selftest_profile_missing_column(map_engine, tmp_path):
    """Job references a column the table doesn't have → schema_error or runtime_error."""
    profile = tmp_path / "bad_col.md"
    profile.write_text(
        "---\n"
        "name: test_missing_col\n"
        "jobs:\n"
        "  - name: bgp_check\n"
        "    type: sql\n"
        "    severity: Warning\n"
        "    query: \"SELECT session_state FROM bgp_neighbors\"\n"
        "---\n# body\n"
    )
    db_file = tmp_path / "t.duckdb"
    import duckdb as _d
    con = _d.connect(str(db_file))
    con.execute("CREATE TABLE bgp_neighbors (device VARCHAR, state VARCHAR)")
    con.close()
    result = map_engine.selftest_profile(str(profile), db_path=str(db_file))
    assert result["ok"] is False
    assert result["jobs"][0]["status"] in ("schema_error", "runtime_error")
    assert "session_state" in (result["jobs"][0]["error"] or "")


def test_selftest_profile_window_placeholder(map_engine, tmp_path):
    """Job using :window placeholder → cutoff binds correctly, no error."""
    profile = tmp_path / "win.md"
    profile.write_text(
        "---\n"
        "name: test_window\n"
        "jobs:\n"
        "  - name: win_check\n"
        "    type: sql\n"
        "    severity: Warning\n"
        "    query: \"SELECT device FROM devices WHERE last_seen > NOW() - INTERVAL :window\"\n"
        "---\n# body\n"
    )
    db_file = tmp_path / "t.duckdb"
    import duckdb as _d
    con = _d.connect(str(db_file))
    con.execute("CREATE TABLE devices (device VARCHAR, last_seen TIMESTAMP)")
    con.close()
    result = map_engine.selftest_profile(str(profile), db_path=str(db_file))
    assert result["ok"] is True


def test_selftest_profile_aggregates_multiple_failures(map_engine, tmp_path):
    """One bad + one good job → ok=False, but only the bad one flagged."""
    profile = tmp_path / "mixed.md"
    profile.write_text(
        "---\n"
        "name: test_mixed\n"
        "jobs:\n"
        "  - name: good_job\n"
        "    type: sql\n"
        "    severity: Info\n"
        "    query: \"SELECT * FROM devices\"\n"
        "  - name: bad_job\n"
        "    type: sql\n"
        "    severity: Warning\n"
        "    query: \"SELECT * FROM nope_does_not_exist\"\n"
        "---\n# body\n"
    )
    db_file = tmp_path / "t.duckdb"
    import duckdb as _d
    con = _d.connect(str(db_file))
    con.execute("CREATE TABLE devices (device VARCHAR)")
    con.close()
    result = map_engine.selftest_profile(str(profile), db_path=str(db_file))
    assert result["ok"] is False
    assert len(result["jobs"]) == 2
    statuses = {j["name"]: j["status"] for j in result["jobs"]}
    assert statuses["good_job"] == "ok"
    assert statuses["bad_job"] in ("schema_error", "runtime_error")

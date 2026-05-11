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

"""Tests for ISSUE-DEAD-SCHEMA-R83-LEFTOVER fix in olav_netops.core.tables.

Verifies ``drop_legacy_tables`` is idempotent and removes the 5 R83-era
ETL tables that no code writes to. Demo7 Ch6 surfaced the regression:
``bgp_neighbors`` had 0 rows, audit profile-author selected it, audit
silently reported "✅ Healthy" off zero data.
"""
from __future__ import annotations

import duckdb
import pytest

from olav_netops.core.tables import (
    _LEGACY_DEAD_TABLES,
    drop_legacy_tables,
)


@pytest.fixture()
def db():
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA netops")
    yield con
    con.close()


def test_dead_table_constant_lists_5_tables():
    """Pin the historical dead-table list. Adding to this list requires
    explicit code review since DROPping production tables is risky."""
    assert set(_LEGACY_DEAD_TABLES) == {
        "interfaces",
        "bgp_neighbors",
        "bgp_routes",
        "ospf_neighbors",
        "routes",
    }


def test_drop_legacy_tables_removes_present_netops_schema(db):
    db.execute("CREATE TABLE netops.bgp_neighbors (device_name VARCHAR)")
    db.execute("CREATE TABLE netops.ospf_neighbors (device_name VARCHAR)")
    db.execute("CREATE TABLE netops.routes (device_name VARCHAR)")
    dropped = drop_legacy_tables(db)
    assert set(dropped) == {
        "netops.bgp_neighbors", "netops.ospf_neighbors", "netops.routes",
    }


def test_drop_legacy_tables_removes_main_schema_too(db):
    """Demo7 finding: dead tables can live in ``main`` (default
    DuckDB schema), not just ``netops`` — drop_legacy must hit both."""
    db.execute("CREATE TABLE main.bgp_neighbors (device_name VARCHAR)")
    db.execute("CREATE TABLE main.routes (device_name VARCHAR)")
    dropped = drop_legacy_tables(db)
    assert set(dropped) == {"main.bgp_neighbors", "main.routes"}


def test_drop_legacy_tables_idempotent(db):
    """Running twice doesn't error and second run reports empty."""
    db.execute("CREATE TABLE netops.bgp_neighbors (device_name VARCHAR)")
    first = drop_legacy_tables(db)
    second = drop_legacy_tables(db)
    assert first == ["netops.bgp_neighbors"]
    assert second == []


def test_drop_legacy_does_not_touch_live_tables(db):
    """Live tables (parsed_outputs, devices etc) must not be dropped
    even though they coexist in the same schemas."""
    db.execute("CREATE TABLE netops.parsed_outputs (device_name VARCHAR)")
    db.execute("CREATE TABLE netops.devices (name VARCHAR)")
    db.execute("CREATE TABLE netops.bgp_neighbors (device_name VARCHAR)")
    drop_legacy_tables(db)
    rem = {
        r[0]
        for r in db.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='netops'"
        ).fetchall()
    }
    assert "parsed_outputs" in rem
    assert "devices" in rem
    assert "bgp_neighbors" not in rem


def test_drop_legacy_returns_empty_on_clean_db(db):
    """No dead tables present → returns empty list, no error."""
    assert drop_legacy_tables(db) == []

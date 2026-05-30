"""
DB data integrity tests for the demo dataset.

No LLM calls — queries DuckDB directly. Runs in <1s.
These tests serve as a pre-gate before the LLM E2E tests in
test_demo_runsheet_82.py: if data is corrupt or missing, the
LLM tests will produce unreliable results regardless.

Run with:
    uv run pytest tests/e2e/test_demo_data_integrity.py -v
or as part of the full runsheet suite:
    RUNSHEET_E2E_ENABLED=1 uv run pytest tests/e2e/ -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
_AGENT_CWD = Path(os.environ.get("RUNSHEET_AGENT_CWD", str(_ROOT)))
_DB = _AGENT_CWD / ".olav" / "databases" / "main.duckdb"

_DB_SKIP = pytest.mark.skipif(
    not _DB.exists(),
    reason="main.duckdb not present — run demo ingest first",
)

try:
    import duckdb as _duckdb
    _con = _duckdb.connect(str(_DB), read_only=True) if _DB.exists() else None
except ImportError:
    _con = None


def _q(sql: str):
    assert _con is not None, "DB connection not available"
    return _con.execute(sql).fetchall()


def _q1(sql: str):
    rows = _q(sql)
    return rows[0][0] if rows else None


# ── Device table integrity ────────────────────────────────────────────────────

@_DB_SKIP
class TestDeviceTableIntegrity:
    """netops.devices — correct counts, vendors, models loaded."""

    def test_total_device_count(self):
        n = _q1("SELECT COUNT(*) FROM netops.devices")
        assert n >= 280, f"Expected ≥280 devices, got {n} — ingest may be incomplete"

    def test_cisco_device_count(self):
        n = _q1("SELECT COUNT(*) FROM netops.devices WHERE LOWER(vendor) = 'cisco'")
        assert n >= 200, f"Expected ≥200 Cisco devices, got {n}"

    def test_no_duplicate_hostnames(self):
        n = _q1(
            "SELECT COUNT(*) FROM ("
            "  SELECT hostname FROM netops.devices GROUP BY hostname HAVING COUNT(*) > 1"
            ")"
        )
        assert n == 0, f"Found {n} duplicate hostnames in netops.devices"

    def test_top_model_present(self):
        rows = _q(
            "SELECT model, COUNT(*) AS n FROM netops.devices "
            "WHERE model IS NOT NULL GROUP BY model ORDER BY n DESC LIMIT 1"
        )
        assert rows, "No model data in netops.devices"
        top_model, top_count = rows[0]
        assert top_count >= 50, (
            f"Top model '{top_model}' has only {top_count} devices — "
            "expected ≥50 for a realistic distribution"
        )

    def test_c9300_model_present(self):
        n = _q1("SELECT COUNT(*) FROM netops.devices WHERE model LIKE 'C9300%'")
        assert n >= 5, f"Expected ≥5 C9300 devices, got {n}"

    def test_c9300_has_version(self):
        rows = _q(
            "SELECT os_version, COUNT(*) FROM netops.devices "
            "WHERE model LIKE 'C9300%' AND os_version IS NOT NULL "
            "GROUP BY os_version ORDER BY 2 DESC LIMIT 1"
        )
        assert rows, "C9300 devices have no os_version data"
        version, count = rows[0]
        assert version.startswith("17."), (
            f"C9300 top version '{version}' unexpected — should be IOS-XE 17.x"
        )


# ── Parsed outputs integrity ──────────────────────────────────────────────────

@_DB_SKIP
class TestParsedOutputsIntegrity:
    """netops.parsed_outputs — snapshots and command coverage."""

    def test_snapshot_count(self):
        n = _q1("SELECT COUNT(DISTINCT snapshot_id) FROM netops.parsed_outputs")
        assert n >= 2, f"Expected ≥2 snapshots, got {n}"

    def test_show_version_present(self):
        n = _q1(
            "SELECT COUNT(*) FROM netops.parsed_outputs WHERE command = 'show version'"
        )
        assert n >= 50, f"Expected ≥50 'show version' rows, got {n}"

    def test_show_inventory_present(self):
        n = _q1(
            "SELECT COUNT(*) FROM netops.parsed_outputs WHERE command = 'show inventory'"
        )
        assert n >= 50, f"Expected ≥50 'show inventory' rows, got {n}"

    def test_cdp_neighbors_present(self):
        n = _q1(
            "SELECT COUNT(*) FROM netops.parsed_outputs "
            "WHERE command IN ('show cdp neighbors', 'show cdp neighbors detail')"
        )
        assert n >= 100, f"Expected ≥100 CDP neighbor rows, got {n}"

    def test_no_null_device_names(self):
        n = _q1(
            "SELECT COUNT(*) FROM netops.parsed_outputs WHERE device_name IS NULL"
        )
        assert n == 0, f"Found {n} rows with NULL device_name in parsed_outputs"


# ── Topology integrity ────────────────────────────────────────────────────────

@_DB_SKIP
class TestTopologyIntegrity:
    """netops.topology_links — graph data is populated."""

    def test_topology_links_count(self):
        n = _q1("SELECT COUNT(*) FROM netops.topology_links")
        assert n >= 100, f"Expected ≥100 topology links, got {n}"

    def test_topology_has_multiple_snapshots(self):
        n = _q1(
            "SELECT COUNT(DISTINCT snapshot_id) FROM netops.topology_links"
        )
        assert n >= 1, f"Expected ≥1 snapshot in topology_links, got {n}"


# ── Bundle ingest integrity ───────────────────────────────────────────────────

@_DB_SKIP
class TestBundleIngestIntegrity:
    """netops.bundle_ingests — at least one completed ingest."""

    def test_at_least_one_ingest(self):
        n = _q1("SELECT COUNT(*) FROM netops.bundle_ingests")
        assert n >= 1, "No bundle ingests found — demo data not loaded"

    def test_ingest_has_outputs(self):
        rows = _q(
            "SELECT commands_count FROM netops.bundle_ingests "
            "ORDER BY ingested_at DESC LIMIT 1"
        )
        assert rows and rows[0][0] >= 100, (
            f"Most recent ingest has only {rows[0][0] if rows else 0} commands — "
            "expected ≥100 for a valid demo snapshot"
        )


# ── Inventory view integrity (CH4 proxy) ─────────────────────────────────────

@_DB_SKIP
class TestInventoryViewIntegrity:
    """v_show_inventory_auto — model PID data available for CH4-style queries."""

    def test_inventory_view_populated(self):
        n = _q1("SELECT COUNT(*) FROM netops.v_show_inventory_auto")
        assert n >= 100, f"Expected ≥100 inventory rows, got {n}"

    def test_c9300_in_inventory(self):
        n = _q1(
            "SELECT COUNT(*) FROM netops.v_show_inventory_auto "
            "WHERE pid LIKE 'C9300%'"
        )
        assert n >= 5, f"Expected ≥5 C9300 inventory entries, got {n}"

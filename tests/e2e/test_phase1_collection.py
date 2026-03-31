"""Phase 1 E2E Gate: Collection Capability Verification.

Gate condition: All 6 lab devices have non-empty parsed_outputs rows in
DuckDB and the most recent snapshot is fresh enough to indicate an active
collection pipeline.

Run with:
    uv run pytest tests/e2e/test_phase1_collection.py -v

Design reference: dev_docs/07. OPENCONFIG_SCHEMA_DESIGN.md §0 (Phase 1)
"""

from __future__ import annotations

import duckdb
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EXPECTED_DEVICES = {"R1", "R2", "R3", "R4", "SW1", "SW2"}
NETCONF_DEVICE = "R2"
NETCONF_DOMAINS = {"netconf_interfaces", "netconf_bgp", "netconf_lldp", "netconf_platform"}

# A snapshot is considered "recent" if it starts with a date >= this prefix.
# Update when a full fresh collect run is performed.
FRESHNESS_MIN_DATE = "2026-03-16"


def _get_connection() -> duckdb.DuckDBPyConnection:
    from pathlib import Path

    db_path = Path(__file__).resolve().parents[2] / ".olav" / "databases" / "main.duckdb"
    assert db_path.exists(), f"main.duckdb not found at {db_path}"
    return duckdb.connect(str(db_path), read_only=True)


# ---------------------------------------------------------------------------
# Test 1: All expected devices appear in parsed_outputs
# ---------------------------------------------------------------------------


def test_all_devices_have_parsed_outputs() -> None:
    """Every lab device must have at least one row in parsed_outputs."""
    con = _get_connection()
    rows = con.execute(
        "SELECT DISTINCT device_name FROM parsed_outputs ORDER BY device_name"
    ).fetchall()
    con.close()

    present = {r[0] for r in rows}
    missing = EXPECTED_DEVICES - present
    assert not missing, (
        f"Phase 1 FAIL — devices with no parsed_outputs: {sorted(missing)}\n"
        "Run 'olav collect --all' to collect fresh data from all devices."
    )


# ---------------------------------------------------------------------------
# Test 2: Each device has a meaningful row count (>5 commands parsed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("device", sorted(EXPECTED_DEVICES))
def test_device_has_minimum_command_coverage(device: str) -> None:
    """Each device should have parsed results for at least 5 commands."""
    con = _get_connection()
    count = con.execute(
        "SELECT COUNT(*) FROM parsed_outputs WHERE device_name = ?", [device]
    ).fetchone()[0]
    con.close()

    assert count >= 5, (
        f"Phase 1 FAIL — {device} has only {count} parsed_outputs row(s); "
        "expected >= 5. Re-collect from device."
    )


# ---------------------------------------------------------------------------
# Test 3: R2 (cisco_ios) has NETCONF-sourced rows (4 OpenConfig domains)
# ---------------------------------------------------------------------------


def test_r2_has_netconf_domains() -> None:
    """R2 must have parsed_outputs rows for all 4 NETCONF/OpenConfig domains."""
    con = _get_connection()
    rows = con.execute(
        "SELECT DISTINCT command FROM parsed_outputs WHERE device_name = ?",
        [NETCONF_DEVICE],
    ).fetchall()
    con.close()

    present_cmds = {r[0] for r in rows}
    missing_domains = NETCONF_DOMAINS - present_cmds
    assert not missing_domains, (
        f"Phase 1 FAIL — R2 is missing NETCONF domains: {sorted(missing_domains)}\n"
        "NETCONF collection for R2 has not been ingested. "
        "Check src/olav/services/netconf_collector.py and re-run collect."
    )


# ---------------------------------------------------------------------------
# Test 4: Most recent snapshot is within the freshness window
# ---------------------------------------------------------------------------


def test_latest_snapshot_is_fresh_enough() -> None:
    """The newest snapshot_id in parsed_outputs must be >= FRESHNESS_MIN_DATE."""
    con = _get_connection()
    latest = con.execute("SELECT MAX(snapshot_id) FROM parsed_outputs").fetchone()[0]
    con.close()

    assert latest is not None, "Phase 1 FAIL — parsed_outputs is empty."
    assert latest >= FRESHNESS_MIN_DATE, (
        f"Phase 1 FAIL — newest snapshot '{latest}' is older than '{FRESHNESS_MIN_DATE}'.\n"
        "Run a fresh 'olav collect --all' to update."
    )


# ---------------------------------------------------------------------------
# Test 5: topology_links has data (CDP/LLDP neighbour discovery worked)
# ---------------------------------------------------------------------------


def test_topology_links_populated() -> None:
    """topology_links must have at least one row (neighbour discovery ran)."""
    con = _get_connection()
    count = con.execute("SELECT COUNT(*) FROM topology_links").fetchone()[0]
    con.close()

    assert count > 0, (
        "Phase 1 FAIL — topology_links is empty. "
        "CDP/LLDP neighbour collection has not been ingested."
    )


# ---------------------------------------------------------------------------
# Test 6: devices table contains all 6 expected lab devices
# ---------------------------------------------------------------------------


def test_devices_table_has_all_lab_devices() -> None:
    """The devices table must reference all 6 lab devices."""
    con = _get_connection()
    rows = con.execute("SELECT name FROM devices ORDER BY name").fetchall()
    con.close()

    registered = {r[0] for r in rows}
    missing = EXPECTED_DEVICES - registered
    assert not missing, (
        f"Phase 1 FAIL — devices table missing: {sorted(missing)}\n"
        "Run 'olav onboard' or import the device inventory."
    )

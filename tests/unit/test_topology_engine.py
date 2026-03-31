"""Unit tests for topology_engine.py (OC-16).

TDD: tests define the contract BEFORE the implementation.
Run first → RED, then implement → GREEN.

Tests cover:
    - extract_lldp_topology()  : parsed_outputs → topology_links
    - schema_catalog field semantics for flat LLDP/CDP rows
    - deduplication on re-run  : upsert semantics

Design reference: dev_docs/01. tracking.md §Phase 3 (OC-16)
"""

from __future__ import annotations

import json

import duckdb
import pytest


# ---------------------------------------------------------------------------
# Fixtures / seed helpers
# ---------------------------------------------------------------------------


def _mem_con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


def _count(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = con.execute(sql).fetchone()
    assert row is not None
    return int(row[0])


def _seed_db(con: duckdb.DuckDBPyConnection) -> None:
    """Create minimal tables: devices, parsed_outputs, topology_links, schema_catalog."""

    con.execute("""
        CREATE TABLE schema_catalog (
            source_type TEXT,
            source_name TEXT,
            platform    TEXT,
            fields      TEXT,
            description TEXT,
            updated_at  TIMESTAMP
        )
    """)
    con.executemany(
        "INSERT INTO schema_catalog VALUES (?,?,?,?,?,?)",
        [
            (
                "textfsm",
                "show lldp neighbors detail",
                "cisco_ios",
                json.dumps(
                    [
                        {"name": "neighbor_name", "type": "str"},
                        {"name": "neighbor_interface", "type": "str"},
                        {"name": "local_interface", "type": "str"},
                    ]
                ),
                "",
                None,
            ),
            (
                "textfsm",
                "show cdp neighbors detail",
                "cisco_ios",
                json.dumps(
                    [
                        {"name": "neighbor_name", "type": "str"},
                        {"name": "neighbor_interface", "type": "str"},
                        {"name": "local_interface", "type": "str"},
                    ]
                ),
                "",
                None,
            ),
        ],
    )

    con.execute("CREATE TABLE devices (name TEXT, platform TEXT)")
    con.executemany(
        "INSERT INTO devices VALUES (?, ?)",
        [
            ("R1", "cisco_ios"),
            ("R3", "cisco_ios"),
            ("SW1", "cisco_ios"),
        ],
    )

    # parsed_outputs — two devices with LLDP neighbours
    con.execute("""
        CREATE TABLE parsed_outputs (
            device_name  TEXT,
            command      TEXT,
            parsed_data  JSON,
            snapshot_id  TEXT,
            raw_output   TEXT,
            PRIMARY KEY (device_name, command, snapshot_id)
        )
    """)
    con.executemany(
        "INSERT INTO parsed_outputs VALUES (?,?,?,?,?)",
        [
            (
                "R3",
                "show lldp neighbors detail",
                json.dumps([
                    {
                        "local_interface": "Ethernet0/0",
                        "neighbor_name": "R1",
                        "neighbor_interface": "ge-0/0/2",
                    }
                ]),
                "2026-03-16_1440",
                "",
            ),
            (
                "SW1",
                "show cdp neighbors detail",
                json.dumps([
                    {
                        "local_interface": "Ethernet0/0",
                        "neighbor_name": "R3",
                        "neighbor_interface": "Ethernet0/1",
                    }
                ]),
                "2026-03-16_1440",
                "",
            ),
        ],
    )

    # topology_links (empty initially)
    con.execute("""
        CREATE TABLE topology_links (
            link_id              TEXT PRIMARY KEY,
            source_device        TEXT,
            source_interface     TEXT,
            destination_device   TEXT,
            destination_interface TEXT,
            discovery_protocol   TEXT,
            link_type            TEXT,
            link_status          TEXT,
            link_speed           TEXT,
            first_seen           TIMESTAMP,
            last_seen            TIMESTAMP,
            last_verified        TIMESTAMP,
            status_changes       INTEGER DEFAULT 0,
            snapshot_id          TEXT,
            platform             TEXT
        )
    """)


# ---------------------------------------------------------------------------
# Test group 1: extract_lldp_topology — output shape
# ---------------------------------------------------------------------------


def test_extract_lldp_topology_inserts_rows() -> None:
    """extract_lldp_topology must populate topology_links from LLDP/CDP data."""
    from olav.core.topology_engine import extract_lldp_topology

    con = _mem_con()
    _seed_db(con)
    result = extract_lldp_topology(con)

    count = _count(con, "SELECT COUNT(*) FROM topology_links")
    assert count > 0, f"topology_links should have rows after extract; result={result}"


def test_extract_lldp_topology_returns_stats() -> None:
    """extract_lldp_topology must return a dict with links_inserted key."""
    from olav.core.topology_engine import extract_lldp_topology

    con = _mem_con()
    _seed_db(con)
    result = extract_lldp_topology(con)

    assert isinstance(result, dict)
    assert "links_inserted" in result, f"Expected 'links_inserted' key; got {result}"
    assert isinstance(result["links_inserted"], int)


def test_extract_lldp_topology_correct_source_device() -> None:
    """source_device must be the device that ran the LLDP command."""
    from olav.core.topology_engine import extract_lldp_topology

    con = _mem_con()
    _seed_db(con)
    extract_lldp_topology(con)

    sources = {r[0] for r in con.execute("SELECT source_device FROM topology_links").fetchall()}
    assert "R3" in sources or "SW1" in sources, f"Expected R3 or SW1 as source; got {sources}"


def test_extract_lldp_topology_correct_destination() -> None:
    """destination_device must be the LLDP-discovered neighbor name."""
    from olav.core.topology_engine import extract_lldp_topology

    con = _mem_con()
    _seed_db(con)
    extract_lldp_topology(con)

    row = con.execute(
        "SELECT destination_device FROM topology_links WHERE source_device = 'R3'"
    ).fetchone()
    assert row is not None, "No link found for R3"
    assert row[0] == "R1", f"Expected destination R1; got {row[0]}"


def test_extract_lldp_topology_protocol_field() -> None:
    """discovery_protocol must be 'LLDP' for lldp commands, 'CDP' for cdp."""
    from olav.core.topology_engine import extract_lldp_topology

    con = _mem_con()
    _seed_db(con)
    extract_lldp_topology(con)

    lldp_row = con.execute(
        "SELECT discovery_protocol FROM topology_links WHERE source_device = 'R3'"
    ).fetchone()
    assert lldp_row is not None
    assert lldp_row[0] == "LLDP", f"Expected LLDP; got {lldp_row[0]}"

    cdp_row = con.execute(
        "SELECT discovery_protocol FROM topology_links WHERE source_device = 'SW1'"
    ).fetchone()
    assert cdp_row is not None
    assert cdp_row[0] == "CDP", f"Expected CDP; got {cdp_row[0]}"


def test_extract_lldp_topology_interfaces_populated() -> None:
    """source_interface and destination_interface must not be empty."""
    from olav.core.topology_engine import extract_lldp_topology

    con = _mem_con()
    _seed_db(con)
    extract_lldp_topology(con)

    row = con.execute(
        "SELECT source_interface, destination_interface FROM topology_links WHERE source_device = 'R3'"
    ).fetchone()
    assert row is not None
    assert row[0], "source_interface should not be empty"
    assert row[1], "destination_interface should not be empty"


# ---------------------------------------------------------------------------
# Test group 2: idempotency
# ---------------------------------------------------------------------------


def test_extract_lldp_topology_idempotent() -> None:
    """Running extract_lldp_topology twice must not duplicate rows."""
    from olav.core.topology_engine import extract_lldp_topology

    con = _mem_con()
    _seed_db(con)
    extract_lldp_topology(con)
    first_count = _count(con, "SELECT COUNT(*) FROM topology_links")

    extract_lldp_topology(con)
    second_count = _count(con, "SELECT COUNT(*) FROM topology_links")

    assert first_count == second_count, (
        f"Rows duplicated on re-run: {first_count} → {second_count}"
    )


# ---------------------------------------------------------------------------
# Test group 3: edge cases
# ---------------------------------------------------------------------------


def test_extract_lldp_topology_empty_parsed_outputs() -> None:
    """Returns zero links_inserted when parsed_outputs has no LLDP rows."""
    from olav.core.topology_engine import extract_lldp_topology

    con = _mem_con()
    _seed_db(con)
    # Delete all LLDP rows
    con.execute("DELETE FROM parsed_outputs")
    result = extract_lldp_topology(con)

    assert result["links_inserted"] == 0


def test_extract_lldp_topology_no_self_loops() -> None:
    """No topology link should have source_device == destination_device."""
    from olav.core.topology_engine import extract_lldp_topology

    con = _mem_con()
    _seed_db(con)
    extract_lldp_topology(con)

    self_loops = _count(
        con,
        "SELECT COUNT(*) FROM topology_links WHERE source_device = destination_device",
    )
    assert self_loops == 0, f"Self-loops detected: {self_loops}"

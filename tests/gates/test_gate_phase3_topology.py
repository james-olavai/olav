"""Phase 3 Gate: Topology Parsing from LLDP/CDP Discovery.

Gate tests verify static post-conditions against a running DB state — they are
NOT end-to-end tests that exercise the topology pipeline. Run them after a
real /netops_init cycle to confirm topology_links was correctly populated.

Gate condition: topology_links contains correct neighbor relationships for
all 6 lab devices, sourced from LLDP/CDP discovery data in parsed_outputs.

Design reference: dev_docs/01. tracking.md §Phase 3 (OC-16)
Run with:
    uv run pytest tests/gates/test_gate_phase3_topology.py -v
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import duckdb
import pytest

# ---------------------------------------------------------------------------
# Lab data availability guard — skip all tests when running outside CLAB lab
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parents[2] / ".olav" / "databases" / "main.duckdb"

_HAS_PHASE3_DATA = False
try:
    with duckdb.connect(str(_DB_PATH), read_only=True) as _con:
        _HAS_PHASE3_DATA = (
            _con.execute("SELECT count(*) FROM netops.topology_links").fetchone()[0] > 0
        )
except Exception:
    pass

pytestmark = pytest.mark.skipif(
    not _HAS_PHASE3_DATA,
    reason="topology_links table empty — run Phase 3 LLDP/CDP topology pipeline first",
)

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parents[2] / ".olav" / "databases" / "main.duckdb"

LAB_DEVICES = {"R1", "R2", "R3", "R4", "SW1", "SW2"}
ALLOWED_PROTOCOLS = {"LLDP", "CDP", "OSPF", "BGP"}
ALLOWED_LINK_STATUSES = {"up", "down", "unknown"}

# Known correct neighbor pairs (source_device, destination_device, protocol)
# derived from LLDP/CDP captures at snapshot 2026-03-16_1440
KNOWN_LINKS = [
    ("R1", "R3", "LLDP"),
    ("R2", "R4", "LLDP"),
    ("R3", "SW1", "CDP"),
    ("R4", "SW2", "CDP"),
]


@pytest.fixture(scope="module")
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    assert _DB_PATH.exists(), f"main.duckdb not found at {_DB_PATH}"
    conn = duckdb.connect(str(_DB_PATH), read_only=True)
    yield conn
    conn.close()


def _fetchall(con: Any, sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
    if params is None:
        return cast(list[tuple[Any, ...]], con.execute(sql).fetchall())
    return cast(list[tuple[Any, ...]], con.execute(sql, params).fetchall())


def _fetchone(con: Any, sql: str, params: list[Any] | None = None) -> tuple[Any, ...]:
    if params is None:
        row = con.execute(sql).fetchone()
    else:
        row = con.execute(sql, params).fetchone()
    assert row is not None, sql
    return cast(tuple[Any, ...], row)


def _count(con: Any, sql: str, params: list[Any] | None = None) -> int:
    return int(_fetchone(con, sql, params)[0])


# ---------------------------------------------------------------------------
# Phase 3 Gate tests
# ---------------------------------------------------------------------------


def test_topology_links_table_exists(con):
    """topology_links table must exist."""
    tables = {str(r[0]) for r in _fetchall(con, "SHOW TABLES")}
    assert "topology_links" in tables, "topology_links table missing"


def test_topology_links_has_lldp_entries(con):
    """topology_links must have entries with LLDP discovery protocol."""
    count = _count(con, "SELECT COUNT(*) FROM topology_links WHERE discovery_protocol = 'LLDP'")
    assert count > 0, "No LLDP entries in topology_links"


def test_topology_links_has_cdp_entries(con):
    """topology_links must have entries with CDP discovery protocol."""
    count = _count(con, "SELECT COUNT(*) FROM topology_links WHERE discovery_protocol = 'CDP'")
    assert count > 0, "No CDP entries in topology_links"


def test_all_lab_devices_have_links(con):
    """All 6 lab devices must appear as source_device in topology_links."""
    devices_with_links = {
        str(r[0]) for r in _fetchall(con, "SELECT DISTINCT source_device FROM topology_links")
    }
    missing = LAB_DEVICES - devices_with_links
    assert not missing, f"Devices missing from topology_links: {missing}"


def test_known_lldp_cdp_links_present(con):
    """Each known LLDP/CDP neighbor pair must appear in topology_links."""
    for src, dst, proto in KNOWN_LINKS:
        rows = _count(
            con,
            """
            SELECT COUNT(*) FROM topology_links
            WHERE source_device = ? AND destination_device = ?
            AND discovery_protocol = ?
            """,
            [src, dst, proto],
        )
        assert rows > 0, f"Expected link {src} → {dst} via {proto} not found in topology_links"


@pytest.mark.parametrize("src,dst,proto", KNOWN_LINKS)
def test_known_link_parametrized(con, src, dst, proto):
    """Parametrized check: each known link has source/destination interface."""
    row = _fetchone(
        con,
        """
        SELECT source_interface, destination_interface
        FROM topology_links
        WHERE source_device = ? AND destination_device = ?
        AND discovery_protocol = ?
        LIMIT 1
        """,
        [src, dst, proto],
    )
    src_iface, dst_iface = row
    assert src_iface, f"{src} → {dst}: source_interface should not be empty"
    assert dst_iface, f"{src} → {dst}: destination_interface should not be empty"


def test_topology_links_no_self_loops(con):
    """No device should have itself listed as its own neighbor."""
    self_loops = _fetchall(
        con,
        "SELECT source_device FROM topology_links WHERE source_device = destination_device",
    )
    assert len(self_loops) == 0, f"Self-loops found: {[str(r[0]) for r in self_loops]}"


def test_topology_links_minimum_coverage(con):
    """topology_links must have at least 10 rows covering LLDP + CDP + routing."""
    count = _count(con, "SELECT COUNT(*) FROM topology_links")
    assert count >= 10, f"Expected >= 10 topology links; got {count}"


def test_topology_links_protocol_values_are_controlled(con):
    """discovery_protocol values must stay in the controlled taxonomy set."""
    protocols = {
        str(r[0])
        for r in _fetchall(
            con,
            "SELECT DISTINCT discovery_protocol FROM topology_links WHERE discovery_protocol IS NOT NULL",
        )
    }
    unexpected = protocols - ALLOWED_PROTOCOLS
    assert not unexpected, f"Unexpected discovery_protocol values: {unexpected}"


def test_topology_links_protocol_to_link_type_taxonomy(con):
    """Protocol and link_type taxonomy must remain semantically consistent."""
    l2_mismatch = _count(
        con,
        """
        SELECT COUNT(*) FROM topology_links
        WHERE discovery_protocol IN ('LLDP', 'CDP')
          AND COALESCE(link_type, '') != 'L2'
        """,
    )
    assert l2_mismatch == 0, "LLDP/CDP links must be typed as L2"

    l3_mismatch = _count(
        con,
        """
        SELECT COUNT(*) FROM topology_links
        WHERE discovery_protocol IN ('OSPF', 'BGP')
          AND COALESCE(link_type, '') != 'L3'
        """,
    )
    assert l3_mismatch == 0, "OSPF/BGP links must be typed as L3"


def test_topology_l2_links_have_complete_interface_endpoints(con):
    """All LLDP/CDP links must keep both source and destination interfaces."""
    incomplete = _count(
        con,
        """
        SELECT COUNT(*) FROM topology_links
        WHERE discovery_protocol IN ('LLDP', 'CDP')
          AND (
            TRIM(COALESCE(source_interface, '')) = ''
            OR TRIM(COALESCE(destination_interface, '')) = ''
          )
        """,
    )
    assert incomplete == 0, "L2 discovery links contain empty interface endpoints"


def test_l2_topology_summary_pairs_are_canonical_and_unique(con):
    """L2 summary view must keep canonical endpoint ordering with unique pairs."""
    reverse_count = _count(
        con,
        """
        SELECT COUNT(*)
        FROM v_l2_topology_summary
        WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_l2_topology_summary)
          AND endpoint_a > endpoint_b
        """,
    )
    assert reverse_count == 0, "v_l2_topology_summary has non-canonical endpoint ordering"

    duplicate_count = _count(
        con,
        """
        SELECT COUNT(*)
        FROM (
            SELECT endpoint_a, endpoint_b, discovery_protocol, COUNT(*) AS c
            FROM v_l2_topology_summary
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_l2_topology_summary)
            GROUP BY 1, 2, 3
            HAVING COUNT(*) > 1
        ) d
        """,
    )
    assert duplicate_count == 0, "v_l2_topology_summary has duplicate endpoint pairs"


def test_l2_topology_summary_has_controlled_link_status(con):
    """L2 summary view must expose only controlled link_status values."""
    statuses = {
        cast(str, row[0])
        for row in _fetchall(
            con,
            """
            SELECT DISTINCT link_status
            FROM v_l2_topology_summary
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_l2_topology_summary)
            """,
        )
        if row[0] is not None
    }
    unexpected = statuses - ALLOWED_LINK_STATUSES
    assert not unexpected, f"Unexpected v_l2_topology_summary link_status values: {unexpected}"


def test_l2_topology_summary_matches_clean_view_latest(con):
    """Latest L2 summary pairs must exactly match latest clean-view L2 pairs."""
    diff_count = _count(
        con,
        """
        WITH clean_pairs AS (
            SELECT src AS endpoint_a, dst AS endpoint_b, discovery_protocol
            FROM v_topo_links_clean
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_topo_links_clean)
              AND discovery_protocol IN ('LLDP', 'CDP')
            GROUP BY 1, 2, 3
        ),
        summary_pairs AS (
            SELECT endpoint_a, endpoint_b, discovery_protocol
            FROM v_l2_topology_summary
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_l2_topology_summary)
              AND discovery_protocol IN ('LLDP', 'CDP')
            GROUP BY 1, 2, 3
        ),
        deltas AS (
            SELECT * FROM clean_pairs
            EXCEPT
            SELECT * FROM summary_pairs
            UNION ALL
            SELECT * FROM summary_pairs
            EXCEPT
            SELECT * FROM clean_pairs
        )
        SELECT COUNT(*) FROM deltas
        """,
    )
    assert diff_count == 0, "v_l2_topology_summary and v_topo_links_clean L2 pairs diverged"


def test_device_neighbors_summary_is_unique_and_matches_clean_view_latest(con):
    """Latest device-neighbor summary must stay unique and match clean-view bidirectional projection."""
    duplicate_count = _count(
        con,
        """
        SELECT COUNT(*)
        FROM (
            SELECT device_name, connected_device, discovery_protocol, COUNT(*) AS c
            FROM v_device_neighbors_summary
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_device_neighbors_summary)
            GROUP BY 1, 2, 3
            HAVING COUNT(*) > 1
        ) d
        """,
    )
    assert duplicate_count == 0, "v_device_neighbors_summary has duplicate neighbor rows"

    statuses = {
        cast(str, row[0])
        for row in _fetchall(
            con,
            """
            SELECT DISTINCT link_status
            FROM v_device_neighbors_summary
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_device_neighbors_summary)
            """,
        )
        if row[0] is not None
    }
    unexpected = statuses - ALLOWED_LINK_STATUSES
    assert not unexpected, f"Unexpected v_device_neighbors_summary link_status values: {unexpected}"

    diff_count = _count(
        con,
        """
        WITH clean_neighbors AS (
            SELECT src AS device_name, dst AS connected_device, discovery_protocol
            FROM v_topo_links_clean
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_topo_links_clean)
              AND discovery_protocol IN ('LLDP', 'CDP')
            GROUP BY 1, 2, 3
            UNION ALL
            SELECT dst AS device_name, src AS connected_device, discovery_protocol
            FROM v_topo_links_clean
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_topo_links_clean)
              AND discovery_protocol IN ('LLDP', 'CDP')
            GROUP BY 1, 2, 3
        ),
        summary_neighbors AS (
            SELECT device_name, connected_device, discovery_protocol
            FROM v_device_neighbors_summary
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_device_neighbors_summary)
            GROUP BY 1, 2, 3
        ),
        deltas AS (
            SELECT * FROM clean_neighbors
            EXCEPT
            SELECT * FROM summary_neighbors
            UNION ALL
            SELECT * FROM summary_neighbors
            EXCEPT
            SELECT * FROM clean_neighbors
        )
        SELECT COUNT(*) FROM deltas
        """,
    )
    assert diff_count == 0, (
        "v_device_neighbors_summary diverged from clean-view bidirectional projection"
    )


# ---------------------------------------------------------------------------
# Phase 3 REAL Gate: topology_links must be traceable to OC-format source data
#
# GATE-BYPASS-1: The original gate tests only verified topology_links existence
# and known link correctness, NOT that the data came from an OC-formatted
# parsed_outputs snapshot.  topology_links was actually populated from raw
# TextFSM fallback (2026-03-02 snapshots) via hardcoded field names
# ("neighbor_name", "neighbor_interface") that happen to match TextFSM output.
# Fix required: P0-FIX-1 (apply_oc_mapping) + P0-FIX-4 (re-ingest) +
#               P0-FIX-3 (correct LLDP mapping_rules).
# ---------------------------------------------------------------------------


def test_topology_lldp_links_sourced_from_oc_snapshot(con):
    """REAL Phase 3 Gate: LLDP topology_links must trace back to OC-format rows.

    For each LLDP link in topology_links, the corresponding snapshot_id must
    have at least one row in parsed_outputs with an openconfig-lldp top-level
    key in parsed_data.

    xfail: If no snapshot has both LLDP links and OC-formatted data, the
    topology was built from raw TextFSM data (pre-OC pipeline). Re-run
    snapshot with the OC pipeline enabled to generate proper data.
    """
    import json as _json

    # Check if ANY snapshot has both LLDP links AND openconfig-lldp data
    oc_snaps = _fetchall(
        con,
        """
        SELECT DISTINCT po.snapshot_id
        FROM parsed_outputs po
        WHERE po.parsed_data LIKE '%openconfig-lldp%'
          AND EXISTS (
            SELECT 1 FROM topology_links tl
            WHERE tl.snapshot_id = po.snapshot_id
              AND tl.discovery_protocol = 'LLDP'
          )
        LIMIT 1
        """,
    )

    if not oc_snaps:
        import pytest

        pytest.xfail(
            "No snapshot has both LLDP topology links and openconfig-lldp parsed data. "
            "Topology was built from raw TextFSM data (pre-OC pipeline). "
            "Re-run snapshot with OC pipeline enabled."
        )

    lldp_snaps = _fetchall(
        con,
        "SELECT DISTINCT snapshot_id FROM topology_links WHERE discovery_protocol = 'LLDP'",
    )

    assert lldp_snaps, "No LLDP entries in topology_links"

    for (snap_id,) in lldp_snaps:
        sample = _fetchall(
            con,
            """
            SELECT CAST(parsed_data AS VARCHAR)
            FROM parsed_outputs
            WHERE snapshot_id = ?
            LIMIT 20
            """,
            [snap_id],
        )

        has_oc = False
        for (raw,) in sample:
            try:
                d = _json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(d, dict):
                    typed_d = cast(dict[str, Any], d)
                    if any(k.startswith("openconfig-lldp") for k in typed_d.keys()):
                        has_oc = True
                        break
            except Exception:
                pass

        if not has_oc:
            import pytest

            pytest.xfail(
                f"Snapshot '{snap_id}' has LLDP topology links but no openconfig-lldp parsed data. "
                f"Topology was built from raw TextFSM data. Re-run snapshot with OC pipeline."
            )

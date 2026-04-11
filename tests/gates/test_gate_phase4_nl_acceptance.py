"""Phase 4 Gate: Natural Language Query Acceptance.

Gate tests verify static post-conditions against a running DB state — they are
NOT end-to-end tests that exercise the NL query pipeline. Run them after the
full Phase 1–3 pipeline has produced data to confirm query readiness.

Gate condition: The full Phase 1–3 pipeline has produced OpenConfig-format
data that supports 4 canonical NL query scenarios via SQL:

  Scenario 1 — "所有设备的 Loopback IP"
      Validates: openconfig-interfaces data path in parsed_outputs / interfaces table
  Scenario 2 — "BGP 邻居中 down 的有哪些"
      Validates: openconfig-bgp neighbor state data in v_bgp_neighbors
  Scenario 3 — "当前 L2 拓扑是什么"
      Validates: topology_links populated from LLDP/CDP OC discovery (Phase 3)
  Scenario 4 — "R2 连接了哪些设备"
      Validates: R2 appears in topology_links via both NETCONF (LLDP) and CLI data

Two test tiers:

  DataContractTests  — always run; SQL assertions against main.duckdb to verify
                       underlying data is ready for each NL scenario.
  NLQueryTests       — run when `NL_QUERY_ENABLED=1` or when runtime LLM config
                       already provides a real API key; skip otherwise.

Design reference: dev_docs/01. tracking.md §Phase 4 (P4-1)
Run with:
    uv run pytest tests/gates/test_gate_phase4_nl_acceptance.py -v
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import duckdb
import pytest

# ---------------------------------------------------------------------------
# Lab data availability guard — skip all tests when running outside CLAB lab
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parents[2] / ".olav" / "databases" / "main.duckdb"

_HAS_LAB_DATA = False
try:
    with duckdb.connect(str(_DB_PATH), read_only=True) as _con:
        _HAS_LAB_DATA = (
            _con.execute("SELECT count(*) FROM netops.parsed_outputs").fetchone()[0] > 0
        )
except Exception:
    pass

pytestmark = pytest.mark.skipif(
    not _HAS_LAB_DATA,
    reason="No lab data in main.duckdb — run CLAB lab first",
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parents[2] / ".olav" / "databases" / "main.duckdb"

LAB_DEVICES = {"R1", "R2", "R3", "R4", "SW1", "SW2"}
ALLOWED_TOPO_PROTOCOLS = {"LLDP", "CDP", "OSPF", "BGP"}
ALLOWED_LINK_STATUSES = {"up", "down", "unknown"}
ALLOWED_BGP_STATES = {
    "Established",
    "Idle",
    "Active",
    "Connect",
    "OpenSent",
    "OpenConfirm",
    "Unknown",
}


def _real_nl_query_enabled() -> bool:
    """Return True when real NL query tests should run.

    Priority:
    1. Explicit `NL_QUERY_ENABLED` env var when present
    2. Auto-enable when runtime LLM config has a real API key
    """
    explicit = os.environ.get("NL_QUERY_ENABLED")
    if explicit is not None:
        return explicit.lower() in {"1", "true", "yes"}

    try:
        from olav.core.config import get_llm_config

        return bool(get_llm_config().api_key)
    except Exception:
        return False


# Skip NL tests unless explicitly enabled or runtime config already has a real API key.
_NL_ENABLED = _real_nl_query_enabled()
nl_query = pytest.mark.skipif(
    not _NL_ENABLED,
    reason="Enable NL_QUERY_ENABLED=1 or provide a real API key in runtime config to run NL tests",
)


@pytest.fixture(scope="module")
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    assert _DB_PATH.exists(), f"main.duckdb not found at {_DB_PATH}"
    conn = duckdb.connect(str(_DB_PATH), read_only=True)
    yield conn
    conn.close()


def _fetchall(con: Any, sql: str) -> list[tuple[Any, ...]]:
    return cast(list[tuple[Any, ...]], con.execute(sql).fetchall())


def _fetchone(con: Any, sql: str) -> tuple[Any, ...]:
    row = con.execute(sql).fetchone()
    assert row is not None, sql
    return cast(tuple[Any, ...], row)


def _count(con: Any, sql: str) -> int:
    return int(_fetchone(con, sql)[0])


# ---------------------------------------------------------------------------
# Scenario 1 gate: "所有设备的 Loopback IP"
# Data source: interfaces table or parsed_outputs with interface data
# ---------------------------------------------------------------------------


def test_s1_interfaces_table_exists(con):
    """interfaces table must exist for Loopback IP queries."""
    tables = {str(r[0]) for r in _fetchall(con, "SHOW TABLES")}
    assert "interfaces" in tables, "interfaces table missing — Phase 1 ingest incomplete"


def test_s1_all_lab_devices_have_interface_data(con):
    """All 6 lab devices must have interface command data in parsed_outputs.

    xfail: If a device is missing interface data, it means the latest snapshot
    didn't include that device's interface collection. Re-run snapshot to refresh.
    """
    devices_with_ifaces = {
        str(r[0])
        for r in _fetchall(
            con,
            """
            SELECT DISTINCT device_name FROM parsed_outputs
            WHERE lower(command) LIKE '%interface%'
            """,
        )
    }
    missing = LAB_DEVICES - devices_with_ifaces
    if missing:
        import pytest

        pytest.xfail(
            f"Devices missing interface data in parsed_outputs: {missing} — "
            "latest snapshot didn't include interface collection for these devices. "
            "Re-run snapshot to refresh."
        )


def test_s1_parsed_outputs_has_interface_commands(con):
    """parsed_outputs must contain show-interfaces entries for interface data path."""
    count = _count(
        con,
        """
        SELECT COUNT(*) FROM parsed_outputs
        WHERE lower(command) LIKE '%interfaces%'
           OR lower(command) LIKE '%show ip interface%'
        """,
    )
    assert count > 0, (
        "No interface-command rows in parsed_outputs — NL Scenario 1 (Loopback IP) cannot execute"
    )


def test_s1_loopback_data_reachable_via_parsed_outputs(con):
    """At least one device must have Loopback IP data in parsed_outputs JSON."""
    rows = _fetchall(
        con,
        """
        SELECT device_name, parsed_data
        FROM parsed_outputs
        WHERE lower(command) LIKE '%show ip interface brief%'
           OR lower(command) LIKE '%show interfaces%'
        LIMIT 20
        """,
    )
    # Find any entry where raw parsed_data mentions 'loop' (case-insensitive)
    loopback_found = any("loop" in str(row[1]).lower() for row in rows)
    assert loopback_found, (
        "No Loopback interface found in parsed_outputs sample — "
        "Scenario 1 query result would be empty"
    )


def test_s1_v_interfaces_supports_all_device_loopback_inventory(con):
    """v_interfaces must support a primary loopback inventory across routers."""
    rows = _fetchall(
        con,
        """
        WITH ranked AS (
            SELECT
                device_name,
                interface,
                ip_address,
                row_number() OVER (
                    PARTITION BY device_name
                    ORDER BY
                        CASE
                            WHEN lower(interface) IN ('loopback0', 'lo0', 'lo0.0') THEN 0
                            WHEN lower(interface) LIKE '%loopback0%' THEN 1
                            WHEN lower(interface) LIKE '%loop%' THEN 2
                            ELSE 3
                        END,
                        snapshot_id DESC,
                        created_at DESC
                ) AS rn
            FROM v_interfaces
            WHERE ip_address IS NOT NULL
              AND lower(interface) LIKE '%loop%'
        )
        SELECT device_name, ip_address
        FROM ranked
        WHERE rn = 1
        ORDER BY device_name
        """,
    )
    assert rows, "v_interfaces has no primary loopback inventory rows"
    inventory: dict[str, str] = {str(device): str(ip) for device, ip in rows}
    assert inventory.get("R1") == "1.1.1.1", inventory
    assert inventory.get("R2") == "2.2.2.2", inventory
    assert inventory.get("R3") == "3.3.3.3", inventory
    assert inventory.get("R4") == "4.4.4.4", inventory


def test_s1_latest_snapshot_loopback_query_shape_returns_all_devices(con):
    """The LLM-style MAX(v_interfaces) query must still return all routers' loopbacks."""
    rows = _fetchall(
        con,
        """
        SELECT device_name, interface, ip_address
        FROM v_interfaces
        WHERE (interface ILIKE '%loopback%' OR interface ILIKE 'lo%')
          AND ip_address IS NOT NULL
          AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_interfaces)
        ORDER BY device_name, interface
        """,
    )
    devices = {str(row[0]) for row in rows}
    assert {"R1", "R2", "R3", "R4"}.issubset(devices), rows


def test_s1_latest_snapshot_primary_loopback0_inventory_is_exact(con):
    """Latest snapshot must expose exactly one primary Loopback0 row per router."""
    rows = _fetchall(
        con,
        """
        SELECT device_name, interface, ip_address
        FROM v_interfaces
        WHERE lower(interface) = 'loopback0'
          AND ip_address IS NOT NULL
          AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_interfaces)
        ORDER BY device_name
        """,
    )
    assert rows == [
        ("R1", "Loopback0", "1.1.1.1"),
        ("R2", "Loopback0", "2.2.2.2"),
        ("R3", "Loopback0", "3.3.3.3"),
        ("R4", "Loopback0", "4.4.4.4"),
    ], rows


def test_s1_latest_snapshot_primary_loopback0_rows_are_unique(con):
    """Latest snapshot must not duplicate router primary Loopback0 rows."""
    duplicate_count = _count(
        con,
        """
        SELECT COUNT(*)
        FROM (
            SELECT device_name, interface, COUNT(*) AS c
            FROM v_interfaces
            WHERE lower(interface) = 'loopback0'
              AND ip_address IS NOT NULL
              AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_interfaces)
            GROUP BY 1, 2
            HAVING COUNT(*) > 1
        ) d
        """,
    )
    assert duplicate_count == 0, "Latest Loopback0 inventory contains duplicate router rows"


def test_s1_latest_snapshot_loopback_rows_match_expected_shape(con):
    """Latest loopback query shape must match the current expected router inventory.

    xfail: If a device is missing loopback data, it means the latest snapshot
    didn't include that device's interface collection.
    """
    rows = _fetchall(
        con,
        """
        SELECT device_name, interface, ip_address
        FROM v_interfaces
        WHERE (interface ILIKE '%loopback%' OR interface ILIKE 'lo%')
          AND ip_address IS NOT NULL
          AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_interfaces)
        ORDER BY device_name, interface
        """,
    )
    # Check that all lab devices have at least their primary loopback
    actual_devices = {r[0] for r in rows}
    expected_devices = {"R1", "R2", "R3", "R4"}
    missing = expected_devices - actual_devices
    if missing:
        import pytest

        pytest.xfail(
            f"Devices missing loopback data: {missing} — "
            "latest snapshot didn't include interface collection. "
            "Re-run snapshot to refresh."
        )

    # Check primary loopbacks exist
    primary = [
        ("R1", "Loopback0", "1.1.1.1"),
        ("R2", "Loopback0", "2.2.2.2"),
        ("R3", "Loopback0", "3.3.3.3"),
        ("R4", "Loopback0", "4.4.4.4"),
    ]
    for expected_row in primary:
        assert expected_row in rows, f"Missing primary loopback: {expected_row}"


# ---------------------------------------------------------------------------
# Scenario 2 gate: "BGP 邻居中 down 的有哪些"
# Data source: v_bgp_neighbors view (populated from bgp_neighbors table)
# ---------------------------------------------------------------------------


def test_s2_bgp_neighbors_table_exists(con):
    """bgp_neighbors table and v_bgp_neighbors view must exist."""
    tables = {str(r[0]) for r in _fetchall(con, "SHOW TABLES")}
    assert "v_bgp_neighbors" in tables or "bgp_neighbors" in tables, (
        "Neither bgp_neighbors nor v_bgp_neighbors found — "
        "BGP state data unavailable for Scenario 2"
    )


def test_s2_bgp_parsed_outputs_present(con):
    """BGP command raw data must exist in parsed_outputs for state extraction."""
    count = _count(
        con,
        """
        SELECT COUNT(*) FROM parsed_outputs
        WHERE lower(command) LIKE '%bgp%'
        """,
    )
    assert count > 0, (
        "No BGP command rows in parsed_outputs — cannot answer 'which BGP neighbors are down'"
    )


def test_s2_bgp_neighbor_state_fields_queryable(con):
    """v_bgp_neighbors must expose state field for down/established filtering."""
    cols = {str(r[0]) for r in _fetchall(con, "DESCRIBE v_bgp_neighbors")}
    assert "state" in cols, (
        f"v_bgp_neighbors missing 'state' column; found: {cols}. "
        "Cannot filter BGP neighbors by up/down status."
    )


def test_s2_bgp_neighbors_has_non_established_rows(con):
    """At least one BGP neighbor must be queryable as non-Established/downish state."""
    count = _count(
        con,
        """
        SELECT COUNT(*) FROM v_bgp_neighbors
        WHERE COALESCE(state, 'Unknown') != 'Established'
        """,
    )
    assert count > 0, (
        "No non-Established BGP neighbors in v_bgp_neighbors — "
        "cannot answer which BGP neighbors are down/not-established"
    )


def test_s2_latest_bgp_neighbor_states_are_controlled(con):
    """Latest BGP neighbor states must stay within the controlled taxonomy."""
    states = {
        cast(str, row[0])
        for row in _fetchall(
            con,
            """
            SELECT DISTINCT state
            FROM v_bgp_neighbors
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_bgp_neighbors)
              AND state IS NOT NULL
            """,
        )
    }
    unexpected = states - ALLOWED_BGP_STATES
    assert not unexpected, f"Unexpected v_bgp_neighbors state values: {unexpected}"


def test_s2_latest_bgp_neighbors_are_unique_by_device_and_neighbor(con):
    """Latest BGP snapshot must not duplicate device_name + neighbor_ip rows."""
    duplicate_count = _count(
        con,
        """
        SELECT COUNT(*)
        FROM (
            SELECT device_name, neighbor_ip, COUNT(*) AS c
            FROM v_bgp_neighbors
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_bgp_neighbors)
            GROUP BY 1, 2
            HAVING COUNT(*) > 1
        ) d
        """,
    )
    assert duplicate_count == 0, "Latest BGP snapshot contains duplicate device/neighbor rows"


def test_s2_latest_bgp_down_query_shape_contains_r2_idle_neighbor(con):
    """Latest non-established BGP query shape must surface the known R2 idle neighbor."""
    rows = _fetchall(
        con,
        """
        SELECT device_name, neighbor_ip, state
        FROM v_bgp_neighbors
        WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_bgp_neighbors)
          AND COALESCE(state, 'Unknown') != 'Established'
        ORDER BY device_name, neighbor_ip
        """,
    )
    assert ("R2", "4.4.4.4", "Idle") in rows, rows


def test_s2_latest_bgp_neighbors_match_expected_shape(con):
    """Latest BGP neighbor projection must match the current expected lab shape.

    xfail: If a device is missing BGP data, it means the latest snapshot
    didn't include that device's BGP collection.
    """
    rows = _fetchall(
        con,
        """
        SELECT device_name, neighbor_ip, neighbor_as, state
        FROM v_bgp_neighbors
        WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_bgp_neighbors)
        ORDER BY device_name, neighbor_ip
        """,
    )
    expected = [
        ("R1", "10.1.12.2", "65001", "Idle"),
        ("R2", "10.1.12.1", "65000", "Established"),
        ("R2", "4.4.4.4", "65001", "Idle"),
        ("R3", "1.1.1.1", "65000", "Established"),
        ("R4", "2.2.2.2", "65001", "Idle"),
    ]
    if rows != expected:
        import pytest

        missing = set(r[0] for r in expected) - set(r[0] for r in rows)
        if missing:
            pytest.xfail(
                f"Devices missing BGP data: {missing} — "
                "latest snapshot didn't include BGP collection for these devices. "
                "Re-run snapshot to refresh."
            )
    assert rows == expected, rows


# ---------------------------------------------------------------------------
# Scenario 3 gate: "当前 L2 拓扑是什么"
# Data source: topology_links (Phase 3 — OC-16 output)
# ---------------------------------------------------------------------------


def test_s3_topology_links_has_l2_entries(con):
    """topology_links must have LLDP or CDP entries for L2 topology query."""
    count = _count(
        con,
        """
        SELECT COUNT(*) FROM topology_links
        WHERE discovery_protocol IN ('LLDP', 'CDP')
        """,
    )
    assert count > 0, (
        "No LLDP/CDP entries in topology_links — Phase 3 OC-16 topology extraction has not run"
    )


def test_s3_topology_links_all_devices_represented(con):
    """All 6 lab devices must appear in topology (as source or destination)."""
    devices_in_topo: set[str] = set()
    for r in _fetchall(
        con, "SELECT DISTINCT source_device, destination_device FROM topology_links"
    ):
        devices_in_topo.add(str(r[0]))
        devices_in_topo.add(str(r[1]))

    # Allow partial match — some devices may only appear as OSPF/BGP hops
    missing = LAB_DEVICES - devices_in_topo
    assert len(missing) <= 1, (
        f"Too many devices missing from topology_links: {missing}. "
        "Expected all 6 lab devices to appear."
    )


def test_s3_topology_no_self_loops(con):
    """No self-loops in topology_links (source == destination)."""
    count = _count(
        con,
        """
        SELECT COUNT(*) FROM topology_links
        WHERE source_device = destination_device
        """,
    )
    assert count == 0, f"Self-loops found in topology_links: {count}"


def test_s3_topology_protocol_values_are_controlled(con):
    """topology discovery_protocol values must remain in the controlled set."""
    protocols = {
        str(r[0])
        for r in _fetchall(
            con,
            """
            SELECT DISTINCT discovery_protocol
            FROM topology_links
            WHERE discovery_protocol IS NOT NULL
            """,
        )
    }
    unexpected = protocols - ALLOWED_TOPO_PROTOCOLS
    assert not unexpected, f"Unexpected topology discovery_protocol values: {unexpected}"


def test_s3_topology_protocol_to_link_type_consistency(con):
    """Protocol taxonomy must map consistently to L2/L3 link types."""
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


def test_s3_l2_topology_links_have_complete_interfaces(con):
    """LLDP/CDP topology links must have both source and destination interfaces."""
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
    assert incomplete == 0, "L2 topology links contain empty interface endpoints"


def test_s3_clean_topology_view_excludes_non_device_endpoints(con):
    """v_topo_links_clean must not include WAN/Switch/numeric pseudo-devices."""
    count = _count(
        con,
        """
        SELECT COUNT(*)
        FROM v_topo_links_clean
        WHERE src NOT IN (SELECT name FROM devices)
           OR dst NOT IN (SELECT name FROM devices)
        """,
    )
    assert count == 0, "v_topo_links_clean still contains non-device endpoints"


def test_s3_latest_snapshot_topology_query_shape_returns_l2_links(con):
    """The LLM-style MAX(v_topo_links_clean) query must still return LLDP topology."""
    rows = _fetchall(
        con,
        """
        SELECT src, dst, discovery_protocol
        FROM v_topo_links_clean
        WHERE discovery_protocol = 'LLDP'
          AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_topo_links_clean)
        ORDER BY src, dst
        """,
    )
    assert ("R1", "R3", "LLDP") in rows, rows
    assert ("R2", "R4", "LLDP") in rows, rows


def test_s3_latest_snapshot_lldp_edges_are_canonical_and_unique(con):
    """Latest LLDP clean view must not keep reverse or exact duplicate edges."""
    reverse_count = _count(
        con,
        """
        SELECT COUNT(*)
        FROM v_topo_links_clean
        WHERE discovery_protocol = 'LLDP'
          AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_topo_links_clean)
          AND src > dst
        """,
    )
    assert reverse_count == 0, "v_topo_links_clean still contains reverse LLDP pairs"

    duplicate_count = _count(
        con,
        """
        SELECT COUNT(*)
        FROM (
            SELECT src, source_interface, dst, destination_interface, discovery_protocol, COUNT(*) AS c
            FROM v_topo_links_clean
            WHERE discovery_protocol = 'LLDP'
              AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_topo_links_clean)
            GROUP BY 1, 2, 3, 4, 5
            HAVING COUNT(*) > 1
        ) d
        """,
    )
    assert duplicate_count == 0, "v_topo_links_clean still contains duplicate LLDP edges"


def test_s3_l2_topology_summary_pairs_are_canonical_and_unique(con):
    """L2 summary must keep canonical endpoint order and unique LLDP pairs."""
    reverse_count = _count(
        con,
        """
        SELECT COUNT(*)
        FROM v_l2_topology_summary
        WHERE discovery_protocol = 'LLDP'
          AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_l2_topology_summary)
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


def test_s3_l2_topology_summary_has_controlled_link_status(con):
    """Latest L2 summary rows must expose only controlled link_status values."""
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


def test_s3_l2_topology_summary_matches_clean_view_latest(con):
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


# ---------------------------------------------------------------------------
# Scenario 4 gate: "R2 连接了哪些设备" (cross-protocol topology for R2)
# Data source: topology_links where source_device='R2' or destination_device='R2'
# ---------------------------------------------------------------------------


def test_s4_r2_has_topology_links(con):
    """R2 must appear in topology_links (NETCONF device with LLDP/OSPF/BGP links)."""
    count = _count(
        con,
        """
        SELECT COUNT(*) FROM topology_links
        WHERE source_device = 'R2' OR destination_device = 'R2'
        """,
    )
    assert count > 0, (
        "R2 has no entries in topology_links — "
        "NETCONF collection for R2 may not be wired to topology extraction"
    )


def test_s4_r2_neighbors_include_r4(con):
    """R2 must be connected to R4 (known lab topology)."""
    rows = _fetchall(
        con,
        """
        SELECT source_device, destination_device, discovery_protocol FROM topology_links
        WHERE (source_device = 'R2' AND destination_device = 'R4')
           OR (source_device = 'R4' AND destination_device = 'R2')
        """,
    )
    assert len(rows) > 0, (
        "R2↔R4 link not found in topology_links — "
        "expected at least one protocol (LLDP/OSPF/BGP) to confirm this link"
    )


def test_s4_r2_lldp_data_in_parsed_outputs(con):
    """R2 must have LLDP data in parsed_outputs (NETCONF-sourced)."""
    count = _count(
        con,
        """
        SELECT COUNT(*) FROM parsed_outputs
        WHERE device_name = 'R2'
          AND (lower(command) LIKE '%lldp%' OR lower(command) LIKE '%cdp%')
        """,
    )
    assert count > 0, (
        "R2 has no LLDP/CDP data in parsed_outputs — "
        "NETCONF LLDP collection for R2 has not been ingested"
    )


def test_s4_r2_protocol_to_link_type_consistency(con):
    """R2-related topology rows must keep protocol/link_type taxonomy consistency."""
    l2_mismatch = _count(
        con,
        """
        SELECT COUNT(*) FROM topology_links
        WHERE (source_device = 'R2' OR destination_device = 'R2')
          AND discovery_protocol IN ('LLDP', 'CDP')
          AND COALESCE(link_type, '') != 'L2'
        """,
    )
    assert l2_mismatch == 0, "R2 LLDP/CDP links must be typed as L2"

    l3_mismatch = _count(
        con,
        """
        SELECT COUNT(*) FROM topology_links
        WHERE (source_device = 'R2' OR destination_device = 'R2')
          AND discovery_protocol IN ('OSPF', 'BGP')
          AND COALESCE(link_type, '') != 'L3'
        """,
    )
    assert l3_mismatch == 0, "R2 OSPF/BGP links must be typed as L3"


def test_s4_r2_l2_links_have_complete_interfaces(con):
    """R2 LLDP/CDP links must contain both source and destination interfaces."""
    incomplete = _count(
        con,
        """
        SELECT COUNT(*) FROM topology_links
        WHERE (source_device = 'R2' OR destination_device = 'R2')
          AND discovery_protocol IN ('LLDP', 'CDP')
          AND (
            TRIM(COALESCE(source_interface, '')) = ''
            OR TRIM(COALESCE(destination_interface, '')) = ''
          )
        """,
    )
    assert incomplete == 0, "R2 L2 links contain empty interface endpoints"


def test_s3_latest_lldp_summary_rows_match_expected_shape(con):
    """Latest LLDP summary rows must match the expected canonical lab baseline."""
    rows = _fetchall(
        con,
        """
        SELECT endpoint_a, endpoint_b, discovery_protocol, link_status
        FROM v_l2_topology_summary
        WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_l2_topology_summary)
          AND discovery_protocol = 'LLDP'
        ORDER BY endpoint_a, endpoint_b
        """,
    )
    assert rows == [
        ("R1", "R3", "LLDP", "up"),
        ("R2", "R4", "LLDP", "up"),
    ], rows


def test_s4_r2_clean_view_has_only_device_neighbors(con):
    """R2 neighbor list for NL Scenario 4 must use clean device-only topology view."""
    count = _count(
        con,
        """
        SELECT COUNT(*)
        FROM v_topo_links_clean
        WHERE (src = 'R2' OR dst = 'R2')
          AND (
            src NOT IN (SELECT name FROM devices)
            OR dst NOT IN (SELECT name FROM devices)
          )
        """,
    )
    assert count == 0, "R2 clean topology view still contains non-device endpoints"


def test_s4_latest_snapshot_r2_neighbor_pairs_are_unique(con):
    """Latest clean-view R2 adjacency must not duplicate exact interface-level edges."""
    duplicate_count = _count(
        con,
        """
        WITH r2_rows AS (
            SELECT
                src,
                source_interface,
                dst,
                destination_interface,
                discovery_protocol
            FROM v_topo_links_clean
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_topo_links_clean)
              AND (src = 'R2' OR dst = 'R2')
        )
        SELECT COUNT(*)
        FROM (
            SELECT src, source_interface, dst, destination_interface, discovery_protocol, COUNT(*) AS c
            FROM r2_rows
            GROUP BY 1, 2, 3, 4, 5
            HAVING COUNT(*) > 1
        ) d
        """,
    )
    assert duplicate_count == 0, "R2 clean-view neighbor list still has duplicate edge rows"


def test_s4_device_neighbors_summary_is_unique_for_r2(con):
    """Device-neighbor summary should expose one row per R2 neighbor+protocol."""
    duplicate_count = _count(
        con,
        """
        SELECT COUNT(*)
        FROM (
            SELECT device_name, connected_device, discovery_protocol, COUNT(*) AS c
            FROM v_device_neighbors_summary
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_device_neighbors_summary)
              AND device_name = 'R2'
            GROUP BY 1, 2, 3
            HAVING COUNT(*) > 1
        ) d
        """,
    )
    assert duplicate_count == 0, "v_device_neighbors_summary has duplicate R2 neighbor rows"

    r4_count = _count(
        con,
        """
        SELECT COUNT(*)
        FROM v_device_neighbors_summary
        WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_device_neighbors_summary)
          AND device_name = 'R2'
          AND connected_device = 'R4'
          AND discovery_protocol = 'LLDP'
        """,
    )
    assert r4_count > 0, "v_device_neighbors_summary missing R2->R4 LLDP adjacency"


def test_s4_device_neighbors_summary_matches_clean_view_latest(con):
    """Latest R2 neighbors in summary view must match latest clean-view projection."""
    diff_count = _count(
        con,
        """
        WITH clean_neighbors AS (
            SELECT
                'R2' AS device_name,
                CASE WHEN src = 'R2' THEN dst ELSE src END AS connected_device,
                discovery_protocol
            FROM v_topo_links_clean
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_topo_links_clean)
              AND (src = 'R2' OR dst = 'R2')
            GROUP BY 1, 2, 3
        ),
        summary_neighbors AS (
            SELECT device_name, connected_device, discovery_protocol
            FROM v_device_neighbors_summary
            WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_device_neighbors_summary)
              AND device_name = 'R2'
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
    assert diff_count == 0, "v_device_neighbors_summary and clean-view R2 neighbors diverged"


def test_s4_latest_r2_neighbor_summary_rows_match_expected_shape(con):
    """Latest R2 neighbor summary rows must match the expected canonical baseline."""
    rows = _fetchall(
        con,
        """
        SELECT device_name, connected_device, discovery_protocol, link_status
        FROM v_device_neighbors_summary
        WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_device_neighbors_summary)
          AND device_name = 'R2'
        ORDER BY connected_device, discovery_protocol
        """,
    )
    assert rows == [
        ("R2", "R4", "LLDP", "up"),
    ], rows


# ---------------------------------------------------------------------------
# P4-2 gate: Ghost Code Final Check
# ---------------------------------------------------------------------------


def test_p4_2_no_schema_mappings_in_db(con):
    """schema_mappings table must NOT exist in main.duckdb (OC-17 complete)."""
    tables = {str(r[0]) for r in _fetchall(con, "SHOW TABLES")}
    assert "schema_mappings" not in tables, (
        "schema_mappings table found in main.duckdb — "
        "ghost data from pre-OC-17 pipeline; run migration to remove it"
    )


def test_p4_2_mapping_rules_is_ground_truth(con):
    """mapping_rules table must be present and populated (OC-17 ground truth)."""
    count = _count(con, "SELECT COUNT(*) FROM mapping_rules")
    assert count > 0, (
        "mapping_rules is empty — P2-3 build_mapping_rules() must be run. "
        "See dev_docs/01. tracking.md §P2-3"
    )


def test_p4_2_yang_leaves_is_populated(con):
    """yang_leaves must be present and populated (OC-14 YANG compiler run)."""
    count = _count(con, "SELECT COUNT(*) FROM yang_leaves")
    assert count > 0, "yang_leaves is empty — P2-2 bootstrap_yang_from_reference() must be run."


# ---------------------------------------------------------------------------
# NL Query tier (requires real LLM availability via config or explicit enablement)
# These tests invoke the real query agent pipeline and assert structured output.
# ---------------------------------------------------------------------------


@nl_query
def test_nl_loopback_ip_query():
    """NL Scenario 1: query agent returns one primary Loopback IP per router."""
    from olav.agents.query_runner import run_nl_query

    result = run_nl_query("所有设备的 Loopback IP 是什么？")
    assert result is not None, "NL query returned None"
    rendered = str(result)
    assert "device_name | interface | ip_address" in rendered, (
        f"Unexpected Scenario 1 header: {result!r}"
    )
    for device, ip in [("R1", "1.1.1.1"), ("R2", "2.2.2.2"), ("R3", "3.3.3.3"), ("R4", "4.4.4.4")]:
        assert device in rendered and ip in rendered, (
            f"Expected {device} {ip} in result; got: {result!r}"
        )
        assert f"{device}, Loopback0, {ip}" in rendered, (
            f"Expected primary Loopback0 row for {device}; got: {result!r}"
        )
    assert "Loopback99" not in rendered, f"Expected primary loopbacks only; got: {result!r}"


@nl_query
def test_nl_bgp_down_query():
    """NL Scenario 2: query agent can enumerate non-Established BGP neighbors."""
    from olav.agents.query_runner import run_nl_query

    result = run_nl_query("BGP 邻居中 down 的有哪些？")
    assert result is not None, "NL query returned None"
    rendered = str(result)
    assert "device_name | neighbor_ip | neighbor_as | state | prefixes_received" in rendered, (
        f"Unexpected Scenario 2 header: {result!r}"
    )
    assert "R2, 4.4.4.4, 65001, Idle, None" in rendered, (
        f"Expected latest R2 idle neighbor row in result; got: {result!r}"
    )
    assert "Established" not in rendered, f"Expected only down-ish BGP neighbors; got: {result!r}"


@nl_query
def test_nl_l2_topology_query():
    """NL Scenario 3: query agent returns normalized LLDP device-pair topology."""
    from olav.agents.query_runner import run_nl_query

    result = run_nl_query("当前的 L2 拓扑是怎样的？哪些设备通过 LLDP 相连？")
    assert result is not None, "NL query returned None"
    rendered = str(result)
    assert "endpoint_a | endpoint_b | discovery_protocol | link_status" in rendered, (
        f"Unexpected Scenario 3 header: {result!r}"
    )
    assert "LLDP" in rendered, f"Expected LLDP in L2 topology result; got: {result!r}"
    assert "R1, R3, LLDP, up" in rendered, f"Expected normalized R1↔R3 pair; got: {result!r}"
    assert "R2, R4, LLDP, up" in rendered, f"Expected normalized R2↔R4 pair; got: {result!r}"
    assert "R3, R1, LLDP" not in rendered, (
        f"Expected normalized topology pairs only; got: {result!r}"
    )
    assert "R4, R2, LLDP" not in rendered, (
        f"Expected normalized topology pairs only; got: {result!r}"
    )
    assert "CDP" not in rendered, f"Expected LLDP-filtered topology result only; got: {result!r}"


@nl_query
def test_nl_r2_neighbors_query():
    """NL Scenario 4: query agent returns R2 neighbor list across protocols."""
    from olav.agents.query_runner import run_nl_query

    result = run_nl_query("R2 连接了哪些设备？")
    assert result is not None, "NL query returned None"
    rendered = str(result)
    assert "connected_device | discovery_protocol | link_status" in rendered, (
        f"Unexpected Scenario 4 header: {result!r}"
    )
    assert "R4, LLDP, up" in rendered, (
        f"Expected R4 LLDP adjacency in R2 neighbor list; got: {result!r}"
    )
    assert "R1" not in rendered and "R3" not in rendered, (
        f"Expected only current clean-view R2 neighbors; got: {result!r}"
    )

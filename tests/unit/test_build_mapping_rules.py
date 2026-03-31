"""Unit tests for build_mapping_rules (P2-3 / OC-13).

TDD: tests define the contract BEFORE the implementation.
Run first → RED, then implement → GREEN.

Tests cover:
  - create_mapping_rules_table()       : DuckDB schema
  - build_mapping_rules()              : schema_catalog × yang_leaves → mapping_rules
    - name-similarity matching           : deterministic baseline when LLM not provided
  - cross-pipeline integrity            : oc_path must exist in yang_leaves

Design reference: dev_docs/07. OPENCONFIG_SCHEMA_DESIGN.md §3.3 (OC-13)
"""

from __future__ import annotations

import json

import duckdb
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mem_con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


def _seed_yang_and_catalog(con: duckdb.DuckDBPyConnection) -> None:
    """Populate yang_leaves + schema_catalog with minimal test data."""
    from olav.core.bootstrap_yang import create_yang_leaves_table

    # yang_leaves — a handful of OpenConfig paths
    create_yang_leaves_table(con)
    yang_rows = [
        (
            "interfaces/interface/config/name",
            "name",
            "string",
            "Interface name",
            "openconfig-interfaces",
        ),
        (
            "interfaces/interface/config/enabled",
            "enabled",
            "boolean",
            "Admin enable",
            "openconfig-interfaces",
        ),
        (
            "interfaces/interface/state/admin-status",
            "admin-status",
            "string",
            "Admin status UP/DOWN",
            "openconfig-interfaces",
        ),
        (
            "interfaces/interface/state/oper-status",
            "oper-status",
            "string",
            "Oper status UP/DOWN",
            "openconfig-interfaces",
        ),
        ("interfaces/interface/state/mtu", "mtu", "uint32", "MTU size", "openconfig-interfaces"),
        (
            "interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/state/ip",
            "ip",
            "string",
            "Interface IPv4 address",
            "openconfig-interfaces",
        ),
        (
            "bgp/neighbors/neighbor/state/session-state",
            "session-state",
            "string",
            "BGP session state",
            "openconfig-bgp",
        ),
        (
            "bgp/neighbors/neighbor/config/peer-as",
            "peer-as",
            "uint32",
            "Peer AS number",
            "openconfig-bgp",
        ),
        (
            "bgp/neighbors/neighbor/state/neighbor-address",
            "neighbor-address",
            "string",
            "BGP peer IP",
            "openconfig-bgp",
        ),
        (
            "lldp/interfaces/interface/neighbors/neighbor/state/system-name",
            "system-name",
            "string",
            "LLDP system name",
            "openconfig-lldp",
        ),
    ]
    con.executemany(
        "INSERT INTO yang_leaves (yang_path, leaf_name, leaf_type, description, module) VALUES (?,?,?,?,?)",
        yang_rows,
    )

    # schema_catalog — minimal textfsm catalog
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
    catalog_rows = [
        (
            "textfsm",
            "show interfaces",
            "cisco_ios",
            json.dumps(
                [
                    {"name": "interface", "type": "str"},
                    {"name": "link_status", "type": "str"},
                    {"name": "admin_status", "type": "str"},
                    {"name": "mtu", "type": "str"},
                ]
            ),
            "",
            None,
        ),
        (
            "textfsm",
            "show ip bgp summary",
            "cisco_ios",
            json.dumps(
                [
                    {"name": "neighbor", "type": "str"},
                    {"name": "peer_as", "type": "str"},
                    {"name": "state", "type": "str"},
                ]
            ),
            "",
            None,
        ),
        (
            "textfsm",
            "show ip interface",
            "cisco_ios",
            json.dumps(
                [
                    {"name": "interface", "type": "str"},
                    {"name": "ip_address", "type": "str"},
                    {"name": "protocol_status", "type": "str"},
                ]
            ),
            "",
            None,
        ),
        (
            "textfsm",
            "show interfaces",
            "juniper_junos",
            json.dumps(
                [
                    {"name": "interface", "type": "str"},
                    {"name": "admin_status", "type": "str"},
                    {"name": "oper_status", "type": "str"},
                ]
            ),
            "",
            None,
        ),
    ]
    con.executemany(
        "INSERT INTO schema_catalog VALUES (?,?,?,?,?,?)",
        catalog_rows,
    )


# ---------------------------------------------------------------------------
# Test group 1: create_mapping_rules_table
# ---------------------------------------------------------------------------


def test_create_mapping_rules_table_schema() -> None:
    """mapping_rules must have the five required columns."""
    from olav.core.schema_engine import create_mapping_rules_table

    con = _mem_con()
    create_mapping_rules_table(con)

    cols = {c[0] for c in con.execute("DESCRIBE mapping_rules").fetchall()}
    required = {"vendor", "command", "src_field", "oc_path", "confidence"}
    missing = required - cols
    assert not missing, f"mapping_rules missing columns: {missing}"
    con.close()


def test_create_mapping_rules_table_idempotent() -> None:
    """create_mapping_rules_table called twice must not raise."""
    from olav.core.schema_engine import create_mapping_rules_table

    con = _mem_con()
    create_mapping_rules_table(con)
    create_mapping_rules_table(con)
    con.close()


# ---------------------------------------------------------------------------
# Test group 2: build_mapping_rules — output shape
# ---------------------------------------------------------------------------


def test_build_mapping_rules_returns_stats() -> None:
    """build_mapping_rules must return a dict with rules_inserted key."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_yang_and_catalog(con)
    create_mapping_rules_table(con)

    result = build_mapping_rules(con, llm=None)

    assert isinstance(result, dict), "build_mapping_rules must return a dict"
    assert "rules_inserted" in result, f"Expected 'rules_inserted' key; got {result}"
    assert isinstance(result["rules_inserted"], int)
    con.close()


def test_build_mapping_rules_inserts_rows() -> None:
    """build_mapping_rules must populate mapping_rules with at least one row per vendor."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_yang_and_catalog(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    row = con.execute("SELECT COUNT(*) FROM mapping_rules").fetchone()
    assert row is not None
    count = int(row[0])
    assert count > 0, "mapping_rules should have rows after build_mapping_rules()"
    con.close()


def test_build_mapping_rules_covers_both_vendors() -> None:
    """Both cisco_ios and juniper_junos must appear in mapping_rules."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_yang_and_catalog(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    vendors = {r[0] for r in con.execute("SELECT DISTINCT vendor FROM mapping_rules").fetchall()}
    assert "cisco_ios" in vendors, f"cisco_ios not found in {vendors}"
    assert "juniper_junos" in vendors, f"juniper_junos not found in {vendors}"
    con.close()


def test_build_mapping_rules_admin_status_matches_interface_path() -> None:
    """admin_status field should map to an interface-related OC path."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_yang_and_catalog(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    rows = con.execute("""
        SELECT oc_path FROM mapping_rules
        WHERE src_field = 'admin_status' AND vendor = 'cisco_ios'
    """).fetchall()
    assert rows, "admin_status for cisco_ios should have a mapping"
    path = rows[0][0]
    assert "admin" in path.lower() or "interface" in path.lower(), (
        f"Expected admin/interface related OC path; got {path!r}"
    )
    con.close()


# ---------------------------------------------------------------------------
# Test group 3: cross-pipeline integrity
# ---------------------------------------------------------------------------


def test_build_mapping_rules_oc_paths_exist_in_yang_leaves() -> None:
    """Every oc_path in mapping_rules must be present in yang_leaves."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_yang_and_catalog(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    orphans = con.execute("""
        SELECT DISTINCT mr.oc_path
        FROM mapping_rules mr
        LEFT JOIN yang_leaves yl ON mr.oc_path = yl.yang_path
        WHERE yl.yang_path IS NULL
    """).fetchall()
    assert len(orphans) == 0, (
        f"mapping_rules contain oc_path values absent from yang_leaves: {[r[0] for r in orphans]}"
    )
    con.close()


def test_build_mapping_rules_is_idempotent() -> None:
    """Running build_mapping_rules twice must not duplicate rows."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_yang_and_catalog(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)
    first_row = con.execute("SELECT COUNT(*) FROM mapping_rules").fetchone()
    assert first_row is not None
    first_count = int(first_row[0])

    build_mapping_rules(con, llm=None)
    second_row = con.execute("SELECT COUNT(*) FROM mapping_rules").fetchone()
    assert second_row is not None
    second_count = int(second_row[0])

    assert first_count == second_count, f"Rows duplicated on re-run: {first_count} → {second_count}"
    con.close()


# ---------------------------------------------------------------------------
# Test group 4: domain-aware filtering (P0-FIX-3)
# ---------------------------------------------------------------------------


def _seed_lldp_catalog_and_yang(con: duckdb.DuckDBPyConnection) -> None:
    """Seed yang_leaves with LLDP + BGP paths and a 'show lldp neighbors' catalog entry.

    The BGP yang_leaves include 'neighbor-address' which can spuriously match
    'neighbor_name' via token overlap.  The fix must ensure LLDP commands
    only match against openconfig-lldp leaves.
    """
    from olav.core.bootstrap_yang import create_yang_leaves_table

    create_yang_leaves_table(con)
    yang_rows = [
        # LLDP leaves
        (
            "lldp/interfaces/interface/neighbors/neighbor/state/system-name",
            "system-name",
            "string",
            "LLDP system name",
            "openconfig-lldp",
        ),
        (
            "lldp/interfaces/interface/neighbors/neighbor/state/port-id",
            "port-id",
            "string",
            "LLDP port ID",
            "openconfig-lldp",
        ),
        (
            "lldp/interfaces/interface/config/name",
            "name",
            "string",
            "Interface name",
            "openconfig-lldp",
        ),
        # BGP leaves (potential false matches)
        (
            "bgp/neighbors/neighbor/state/neighbor-address",
            "neighbor-address",
            "string",
            "BGP peer IP",
            "openconfig-bgp",
        ),
        (
            "bgp/neighbors/neighbor/config/peer-as",
            "peer-as",
            "uint32",
            "Peer AS number",
            "openconfig-bgp",
        ),
        (
            "bgp/neighbors/neighbor/state/session-state",
            "session-state",
            "string",
            "BGP session state",
            "openconfig-bgp",
        ),
    ]
    con.executemany(
        "INSERT INTO yang_leaves (yang_path, leaf_name, leaf_type, description, module) VALUES (?,?,?,?,?)",
        yang_rows,
    )

    con.execute("""
        CREATE TABLE IF NOT EXISTS schema_catalog (
            source_type TEXT,
            source_name TEXT,
            platform    TEXT,
            fields      TEXT,
            description TEXT,
            updated_at  TIMESTAMP
        )
    """)
    con.execute(
        "INSERT INTO schema_catalog VALUES (?,?,?,?,?,?)",
        [
            "textfsm",
            "show lldp neighbors",
            "cisco_ios",
            json.dumps(
                [
                    {"name": "neighbor_name", "type": "str"},
                    {"name": "local_interface", "type": "str"},
                    {"name": "neighbor_interface", "type": "str"},
                ]
            ),
            "",
            None,
        ],
    )


def test_lldp_command_fields_map_to_lldp_module() -> None:
    """Fields from 'show lldp neighbors' MUST map to openconfig-lldp paths, not BGP."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_lldp_catalog_and_yang(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    rows = con.execute("""
        SELECT src_field, oc_path FROM mapping_rules
        WHERE command = 'show lldp neighbors'
    """).fetchall()

    assert rows, "Expected mapping_rules for 'show lldp neighbors'"

    for src_field, oc_path in rows:
        assert "lldp" in oc_path, (
            f"LLDP command field '{src_field}' mapped to non-LLDP path: {oc_path!r}. "
            f"Expected an openconfig-lldp path."
        )
    con.close()


def test_lldp_filtering_does_not_affect_bgp_commands() -> None:
    """BGP commands must still map to openconfig-bgp paths (no collateral damage)."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_lldp_catalog_and_yang(con)

    # Also add a BGP catalog entry
    con.execute(
        "INSERT INTO schema_catalog VALUES (?,?,?,?,?,?)",
        [
            "textfsm",
            "show ip bgp summary",
            "cisco_ios",
            json.dumps(
                [
                    {"name": "neighbor", "type": "str"},
                    {"name": "peer_as", "type": "str"},
                    {"name": "state", "type": "str"},
                ]
            ),
            "",
            None,
        ],
    )

    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    bgp_rows = con.execute("""
        SELECT src_field, oc_path FROM mapping_rules
        WHERE command = 'show ip bgp summary'
    """).fetchall()

    assert bgp_rows, "Expected mapping_rules for 'show ip bgp summary'"

    for src_field, oc_path in bgp_rows:
        assert "bgp" in oc_path, (
            f"BGP command field '{src_field}' mapped to non-BGP path: {oc_path!r}."
        )
    con.close()


def test_cdp_command_also_filtered_to_lldp_module() -> None:
    """CDP is discovery-protocol equivalent — should also filter to openconfig-lldp."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_lldp_catalog_and_yang(con)

    # Add a CDP catalog entry
    con.execute(
        "INSERT INTO schema_catalog VALUES (?,?,?,?,?,?)",
        [
            "textfsm",
            "show cdp neighbors detail",
            "cisco_ios",
            json.dumps(
                [
                    {"name": "neighbor_name", "type": "str"},
                    {"name": "local_interface", "type": "str"},
                ]
            ),
            "",
            None,
        ],
    )

    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    cdp_rows = con.execute("""
        SELECT src_field, oc_path FROM mapping_rules
        WHERE command = 'show cdp neighbors detail'
    """).fetchall()

    assert cdp_rows, "Expected mapping_rules for 'show cdp neighbors detail'"

    for src_field, oc_path in cdp_rows:
        assert "lldp" in oc_path, (
            f"CDP command field '{src_field}' mapped to non-LLDP path: {oc_path!r}."
        )
    con.close()


def test_lldp_field_alias_disambiguation() -> None:
    """_FIELD_ALIASES must resolve neighbor_interface→port-id, local_interface→config/name,
    neighbor_name→system-name without token-similarity confusion."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_lldp_catalog_and_yang(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    expected = {
        "neighbor_name": "lldp/interfaces/interface/neighbors/neighbor/state/system-name",
        "neighbor_interface": "lldp/interfaces/interface/neighbors/neighbor/state/port-id",
        "local_interface": "lldp/interfaces/interface/config/name",
    }

    for src_field, expected_oc_path in expected.items():
        rows = con.execute(
            "SELECT oc_path FROM mapping_rules WHERE command = 'show lldp neighbors' AND src_field = ?",
            [src_field],
        ).fetchall()
        assert rows, f"No mapping_rule for src_field={src_field!r}"
        actual = rows[0][0]
        assert actual == expected_oc_path, (
            f"Field {src_field!r} mapped to {actual!r}, expected {expected_oc_path!r}"
        )
    con.close()


def test_build_mapping_rules_confidence_field_is_string() -> None:
    """Confidence column must be a non-empty string (e.g. 'name_similarity')."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_yang_and_catalog(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    rows = con.execute("SELECT confidence FROM mapping_rules LIMIT 1").fetchall()
    assert rows, "No rows in mapping_rules"
    assert rows[0][0], "confidence should not be empty"
    con.close()


def test_interface_ip_address_maps_to_openconfig_interface_ip() -> None:
    """Interface IP fields must map to interface IPv4 address paths, not BGP neighbor paths."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_yang_and_catalog(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    rows = con.execute(
        """
        SELECT oc_path FROM mapping_rules
        WHERE command = 'show ip interface' AND src_field = 'ip_address'
        """
    ).fetchall()
    assert rows, "Expected mapping rule for show ip interface/ip_address"
    assert rows[0][0] == 'interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/state/ip'
    con.close()


def test_bgp_state_maps_to_session_state() -> None:
    """BGP state fields must map to session-state, not neighbor-address."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_yang_and_catalog(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    rows = con.execute(
        """
        SELECT oc_path FROM mapping_rules
        WHERE command = 'show ip bgp summary' AND src_field = 'state'
        """
    ).fetchall()
    assert rows, "Expected mapping rule for show ip bgp summary/state"
    assert rows[0][0] == 'bgp/neighbors/neighbor/state/session-state'
    con.close()


def test_bgp_peer_as_maps_to_peer_as() -> None:
    """BGP peer_as fields must map to peer-as, not global AS."""
    from olav.core.schema_engine import build_mapping_rules, create_mapping_rules_table

    con = _mem_con()
    _seed_yang_and_catalog(con)
    create_mapping_rules_table(con)
    build_mapping_rules(con, llm=None)

    rows = con.execute(
        """
        SELECT oc_path FROM mapping_rules
        WHERE command = 'show ip bgp summary' AND src_field = 'peer_as'
        """
    ).fetchall()
    assert rows, "Expected mapping rule for show ip bgp summary/peer_as"
    assert rows[0][0] == 'bgp/neighbors/neighbor/config/peer-as'
    con.close()

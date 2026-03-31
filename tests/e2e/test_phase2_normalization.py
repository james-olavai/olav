"""Phase 2 E2E Gate: Data Normalization (OpenConfig).

Gate condition: The normalization pipeline has populated:
  1. `yang_leaves` — YANG Golden Dict compiled from OpenConfig YANG sources
  2. `mapping_rules` — field-level schema mappings (vendor → OC path)
  3. At least one `parsed_outputs` row pairs with a `mapping_rule` entry

These tests are deliberately RED until the normalization pipeline (P2-2/P2-3)
is wired into the ingest flow.

Run with:
    uv run pytest tests/e2e/test_phase2_normalization.py -v

Design reference: dev_docs/07. OPENCONFIG_SCHEMA_DESIGN.md §Phase 2
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parents[2] / ".olav" / "databases" / "main.duckdb"


@pytest.fixture(scope="module")
def con():
    assert _DB_PATH.exists(), f"main.duckdb not found at {_DB_PATH}"
    conn = duckdb.connect(str(_DB_PATH), read_only=True)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Phase 2 Gate: yang_leaves (OC-14)
# ---------------------------------------------------------------------------


def test_yang_leaves_table_exists(con):
    """yang_leaves table must exist (bootstrap_yang.py has been run)."""
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    assert "yang_leaves" in tables, (
        "yang_leaves table missing — run bootstrap_yang() to populate it. "
        "See P2-2 in dev_docs/01. tracking.md"
    )


def test_yang_leaves_has_rows(con):
    """yang_leaves must contain at least interface-related paths."""
    count = con.execute("SELECT COUNT(*) FROM yang_leaves").fetchone()[0]
    assert count > 0, "yang_leaves is empty — bootstrap_yang() may have failed"


def test_yang_leaves_interface_paths_present(con):
    """Critical OC interface paths must exist in yang_leaves."""
    rows = con.execute(
        """
        SELECT yang_path FROM yang_leaves
        WHERE yang_path LIKE '%interfaces%'
        LIMIT 1
        """
    ).fetchall()
    assert len(rows) > 0, "No interfaces-related yang_leaves rows found"


def test_yang_leaves_has_required_columns(con):
    """yang_leaves schema must include all required columns."""
    cols = {row[0] for row in con.execute("DESCRIBE yang_leaves").fetchall()}
    required = {"yang_path", "leaf_name", "leaf_type", "description", "module"}
    missing = required - cols
    assert not missing, f"yang_leaves missing columns: {missing}"


# ---------------------------------------------------------------------------
# Phase 2 Gate: mapping_rules (OC-13)
# ---------------------------------------------------------------------------


def test_mapping_rules_table_exists(con):
    """mapping_rules table must exist (OC-13 schema_engine has been run)."""
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    assert "mapping_rules" in tables, (
        "mapping_rules table missing — run schema_engine to generate mappings. "
        "See P2-3 in dev_docs/01. tracking.md"
    )


def test_mapping_rules_has_rows(con):
    """mapping_rules must contain at least one vendor → OC path entry."""
    count = con.execute("SELECT COUNT(*) FROM mapping_rules").fetchone()[0]
    assert count > 0, "mapping_rules is empty — schema_engine may have failed"


def test_mapping_rules_cisco_ios_coverage(con):
    """mapping_rules must cover cisco_ios (the majority vendor in the lab)."""
    count = con.execute("SELECT COUNT(*) FROM mapping_rules WHERE vendor = 'cisco_ios'").fetchone()[
        0
    ]
    assert count > 0, "No cisco_ios mapping rules found — incomplete normalization"


def test_mapping_rules_juniper_coverage(con):
    """mapping_rules must cover juniper_junos (R1 device)."""
    count = con.execute(
        "SELECT COUNT(*) FROM mapping_rules WHERE vendor = 'juniper_junos'"
    ).fetchone()[0]
    assert count > 0, "No juniper_junos mapping rules found"


def test_mapping_rules_schema_has_required_columns(con):
    """mapping_rules schema must include required columns."""
    cols = {row[0] for row in con.execute("DESCRIBE mapping_rules").fetchall()}
    required = {"vendor", "command", "src_field", "oc_path", "confidence"}
    missing = required - cols
    assert not missing, f"mapping_rules missing columns: {missing}"


# ---------------------------------------------------------------------------
# Phase 2 Gate: cross-pipeline integrity
# ---------------------------------------------------------------------------


def test_mapping_rules_reference_valid_yang_paths(con):
    """Every mapping_rule.oc_path must correspond to a yang_leaves.yang_path."""
    orphans = con.execute(
        """
        SELECT DISTINCT mr.oc_path
        FROM mapping_rules mr
        LEFT JOIN yang_leaves yl ON mr.oc_path = yl.yang_path
        WHERE yl.yang_path IS NULL
        LIMIT 5
        """
    ).fetchall()
    assert len(orphans) == 0, (
        f"mapping_rules contain oc_path values absent from yang_leaves: {[r[0] for r in orphans]}"
    )


# ---------------------------------------------------------------------------
# Phase 2 Gate: parsed_outputs pipeline wiring (P2-4 / P2-6)
# ---------------------------------------------------------------------------


def test_parsed_outputs_table_exists(con):
    """parsed_outputs table must exist."""
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    assert "parsed_outputs" in tables, "parsed_outputs table missing"


def test_parsed_outputs_has_all_6_lab_devices(con):
    """parsed_outputs must contain rows for all 6 lab devices."""
    count = con.execute("SELECT COUNT(DISTINCT device_name) FROM parsed_outputs").fetchone()[0]
    assert count >= 6, f"parsed_outputs only covers {count} devices — expected ≥6 lab devices"


def test_parsed_outputs_has_required_columns(con):
    """parsed_outputs schema must include all pipeline-required columns."""
    cols = {row[0] for row in con.execute("DESCRIBE parsed_outputs").fetchall()}
    required = {"device_name", "command", "parsed_data", "raw_output", "snapshot_id"}
    missing = required - cols
    assert not missing, f"parsed_outputs missing columns: {missing}"


def test_parsed_outputs_mapping_coverage_breadth(con):
    """At least 5 commands present in parsed_outputs must have matching mapping_rules entries.

    This verifies the normalization pipeline has broad enough coverage to be
    useful — not just covering one vendor/command edge case.
    """
    count = con.execute(
        """
        SELECT COUNT(DISTINCT po.command)
        FROM parsed_outputs po
        JOIN mapping_rules mr ON mr.command = po.command
        WHERE json_array_length(po.parsed_data) > 0
        """
    ).fetchone()[0]
    assert count >= 5, (
        f"Only {count} commands in parsed_outputs have mapping_rules coverage — "
        "expected ≥5 for meaningful OC normalization"
    )


@pytest.mark.xfail(reason="Phase 2 quarantine: contradicts doc 07/08 target contracts")
def test_apply_oc_mapping_integration_remaps_real_data(con):
    """Integration gate (P2-4): apply_oc_mapping() must produce openconfig-* keys
    from fresh TextFSM records re-parsed via ntc_templates from raw_output.

    Pipeline: raw CLI output → ntc_templates parse → apply_oc_mapping → OC nested JSON
    """
    from ntc_templates.parse import parse_output
    from olav.core.normalization import apply_oc_mapping

    row = con.execute(
        """
        SELECT po.raw_output, d.platform
        FROM parsed_outputs po
        JOIN devices d ON d.name = po.device_name
        WHERE po.command = 'show interfaces'
          AND d.platform = 'cisco_ios'
          AND po.raw_output IS NOT NULL
          AND LENGTH(po.raw_output) > 0
        LIMIT 1
        """
    ).fetchone()
    assert row is not None, (
        "No cisco_ios 'show interfaces' rows with raw_output in parsed_outputs — "
        "run a full sync on a recent snapshot first"
    )

    raw_output, platform = row
    records = parse_output(platform=platform, command="show interfaces", data=raw_output)
    assert isinstance(records, list) and len(records) > 0, (
        f"ntc_templates parse_output returned empty for cisco_ios/show interfaces"
    )

    original_keys = set(records[0].keys())
    remapped = apply_oc_mapping(records, platform, "show interfaces", con)

    assert remapped, "apply_oc_mapping returned empty list"
    remapped_keys = set(remapped[0].keys())
    new_oc_keys = {k for k in remapped_keys if k.startswith("openconfig-")}

    assert len(new_oc_keys) > 0, (
        f"apply_oc_mapping produced no openconfig-* top-level keys.\n"
        f"  original keys (from ntc_templates): {sorted(original_keys)}\n"
        f"  remapped keys: {sorted(remapped_keys)}\n"
        f"  mapping_rules src_fields for (cisco_ios, show interfaces): "
        + str(
            [
                r[0]
                for r in con.execute(
                    "SELECT src_field FROM mapping_rules "
                    "WHERE vendor='cisco_ios' AND command='show interfaces' LIMIT 5"
                ).fetchall()
            ]
        )
    )


# ---------------------------------------------------------------------------
# Phase 2 REAL Gate: parsed_outputs must contain actual OC top-level keys
#
# This test enforces the original gate design (07. OPENCONFIG_SCHEMA_DESIGN.md):
#   "assert every row's parsed_data JSON contains correct OpenConfig
#    top-level keys (openconfig-interfaces:interfaces, openconfig-bgp:bgp, ...)"
#
# GATE-BYPASS-1: This assertion was ABSENT from the original test file, which
# allowed Phase 2 to be marked "complete" while parsed_outputs contained 0 OC rows.
# Fix required: P0-FIX-1 (apply_oc_mapping nested struct) + P0-FIX-3 (mapping_rules LLDP).
# ---------------------------------------------------------------------------


def test_parsed_outputs_latest_snapshot_has_oc_keys(con):
    """REAL Phase 2 Gate: latest snapshot rows must contain openconfig-* top-level keys.

    This is the gate condition from the original design document (Phase 2):
        parsed_outputs.parsed_data must be a JSON object with at least one key
        matching 'openconfig-interfaces', 'openconfig-bgp', or 'openconfig-lldp'.
    """
    import json as _json

    rows = con.execute(
        """
        SELECT CAST(parsed_data AS VARCHAR)
        FROM parsed_outputs
        WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM parsed_outputs)
          AND device_name IN ('R1','R2','R3','R4','SW1','SW2')
        LIMIT 50
        """
    ).fetchall()

    assert rows, "No rows in latest parsed_outputs snapshot"

    oc_rows = 0
    for (raw,) in rows:
        try:
            d = _json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(d, dict) and any(k.startswith("openconfig-") for k in d):
                oc_rows += 1
        except Exception:
            pass

    assert oc_rows > 0, (
        f"GATE-BYPASS-1: 0/{len(rows)} rows in latest snapshot contain "
        f"openconfig-* top-level keys. "
        f"parsed_outputs data is still raw vendor TextFSM JSON. "
        f"Fix: P0-FIX-1 in dev_docs/00. issues.md."
    )


def test_mapping_rules_lldp_fields_map_to_lldp_module(con):
    """LLDP TextFSM fields must map to openconfig-lldp OC paths, not bgp or ospf."""
    wrong_module_rows = con.execute(
        """
        SELECT src_field, oc_path
        FROM mapping_rules
        WHERE (command LIKE '%lldp%' OR command LIKE '%cdp%')
          AND src_field IN ('neighbor_name', 'neighbor_interface', 'local_interface')
          AND oc_path NOT LIKE '%lldp%'
        """
    ).fetchall()

    assert len(wrong_module_rows) == 0, (
        f"GATE-BYPASS-1: LLDP fields mapped to wrong OC module:\n"
        + "\n".join(f"  {src} -> {oc}" for src, oc in wrong_module_rows)
    )

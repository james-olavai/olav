#!/usr/bin/env python3
"""GATE-BYPASS-1 migration: rebuild mapping_rules, re-normalize parsed_outputs, re-extract topology.

Steps:
  1. Clear and rebuild mapping_rules with domain-aware filtering (P0-FIX-3).
  2. Re-normalize every parsed_outputs row via apply_oc_mapping (P0-FIX-1).
  3. Delete LLDP/CDP topology_links, re-extract from OC-structured data (P0-FIX-4).

Usage:
  uv run python scripts/migrate_oc_pipeline.py [--dry-run]
"""

from __future__ import annotations

import json
import logging
import sys

import duckdb

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _base_table(con: duckdb.DuckDBPyConnection, table_name: str) -> str:
    has_netops = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema='netops' AND table_name=? AND table_type='BASE TABLE'",
        [table_name],
    ).fetchone()[0]
    return f"netops.{table_name}" if has_netops else table_name


def _get_device_platform_map(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    rows = con.execute("SELECT name, platform FROM devices WHERE platform IS NOT NULL").fetchall()
    return {name: platform for name, platform in rows}


_XMLNS_TO_OC_MODULE: dict[str, str] = {
    "http://openconfig.net/yang/lldp": "openconfig-lldp",
    "http://openconfig.net/yang/interfaces": "openconfig-interfaces",
    "http://openconfig.net/yang/bgp": "openconfig-bgp",
    "http://openconfig.net/yang/platform": "openconfig-platform",
    "http://openconfig.net/yang/network-instance": "openconfig-network-instance",
}


def reseed_yang_leaves(con: duckdb.DuckDBPyConnection) -> int:
    """Re-seed yang_leaves from the updated OPENCONFIG_YANG_REFERENCE constant."""
    from olav.core.bootstrap_yang import bootstrap_yang_from_reference
    from olav.core.schema_engine import OPENCONFIG_YANG_REFERENCE

    result = bootstrap_yang_from_reference(OPENCONFIG_YANG_REFERENCE, con)
    count = result.get("leaves_inserted", 0)
    logger.info("yang_leaves re-seeded: %d leaves from reference", count)
    return count


def _unwrap_netconf_rpc_reply(data: dict) -> dict | None:
    """Unwrap netconf rpc-reply envelope and re-key with OC module prefix.

    Input format::

        {"rpc-reply": {"data": {"lldp": {"@xmlns": "http://openconfig.net/yang/lldp", ...}}}}

    Returns ``{"openconfig-lldp": {"lldp": {...}}}`` or None if data is empty/null.
    """
    rpc_reply = data.get("rpc-reply", data)
    inner = rpc_reply.get("data") if isinstance(rpc_reply, dict) else None
    if not inner or not isinstance(inner, dict):
        return None

    result: dict = {}
    for key, value in inner.items():
        if key.startswith("@"):
            continue
        xmlns = value.get("@xmlns") if isinstance(value, dict) else None
        oc_module = _XMLNS_TO_OC_MODULE.get(xmlns, "") if xmlns else ""
        if oc_module:
            result[oc_module] = {key: value}
        else:
            for _url, mod in _XMLNS_TO_OC_MODULE.items():
                if key in mod:
                    result[mod] = {key: value}
                    break

    return result if result else None


def normalize_netconf_rows(con: duckdb.DuckDBPyConnection, dry_run: bool = False) -> int:
    """Unwrap netconf rpc-reply rows in parsed_outputs into OC-keyed dicts."""
    rows = con.execute(
        "SELECT device_name, command, CAST(parsed_data AS VARCHAR), snapshot_id "
        "FROM parsed_outputs WHERE command LIKE 'netconf_%'"
    ).fetchall()

    updated = 0
    for device_name, command, parsed_data_raw, snapshot_id in rows:
        try:
            parsed = (
                json.loads(parsed_data_raw) if isinstance(parsed_data_raw, str) else parsed_data_raw
            )
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(parsed, dict):
            continue

        if any(k.startswith("openconfig-") for k in parsed):
            continue

        oc_data = _unwrap_netconf_rpc_reply(parsed)
        if not oc_data:
            logger.debug("normalize_netconf: skip %s/%s (empty/null data)", device_name, command)
            continue

        new_data = json.dumps(oc_data)
        if not dry_run:
            tbl = _base_table(con, "parsed_outputs")
            con.execute(
                f"UPDATE {tbl} SET parsed_data = ?::JSON "
                f"WHERE device_name = ? AND command = ? AND snapshot_id = ?",
                [new_data, device_name, command, snapshot_id],
            )
        updated += 1
        logger.debug("normalize_netconf: %s/%s → %s", device_name, command, list(oc_data.keys()))

    logger.info(
        "netconf rows normalized: %d rows %s", updated, "(dry-run)" if dry_run else "updated"
    )
    return updated


def rebuild_mapping_rules(con: duckdb.DuckDBPyConnection) -> int:
    from olav.core.schema_engine import build_mapping_rules

    con.execute("DELETE FROM mapping_rules")
    result = build_mapping_rules(con, llm=None)
    count = result.get("rules_inserted", 0)
    logger.info("mapping_rules rebuilt: %d rules inserted", count)
    return count


_FALLBACK_PLATFORMS = ["cisco_ios", "juniper_junos", "arista_eos", "cisco_nxos"]


def _try_parse_output(platform: str, command: str, raw_output: str) -> list[dict] | None:
    from ntc_templates.parse import parse_output

    try:
        records = parse_output(platform=platform, command=command, data=raw_output)
        if isinstance(records, list) and records:
            return records
    except Exception:
        pass

    for fallback in _FALLBACK_PLATFORMS:
        if fallback == platform:
            continue
        try:
            records = parse_output(platform=fallback, command=command, data=raw_output)
            if isinstance(records, list) and records:
                logger.debug(
                    "Fallback parse: %s/%s succeeded with %s template",
                    platform,
                    command,
                    fallback,
                )
                return records
        except Exception:
            continue
    return None


def renormalize_parsed_outputs(con: duckdb.DuckDBPyConnection, dry_run: bool = False) -> int:
    from olav.core.normalization import apply_oc_mapping

    platform_map = _get_device_platform_map(con)

    rows = con.execute(
        "SELECT device_name, command, CAST(raw_output AS VARCHAR), snapshot_id "
        "FROM parsed_outputs "
        "WHERE command NOT LIKE 'netconf_%'"
    ).fetchall()

    updated = 0
    skipped_no_platform = 0
    skipped_no_raw = 0
    skipped_parse_fail = 0
    skipped_no_oc = 0

    for device_name, command, raw_output, snapshot_id in rows:
        platform = platform_map.get(device_name)
        if not platform:
            skipped_no_platform += 1
            continue

        if not raw_output or not raw_output.strip():
            skipped_no_raw += 1
            continue

        records = _try_parse_output(platform, command, raw_output)
        if not records:
            skipped_parse_fail += 1
            continue

        oc_result = apply_oc_mapping(records, platform, command, con)

        if not oc_result:
            skipped_no_oc += 1
            continue

        has_oc = any(
            isinstance(r, dict)
            and any(k.startswith("openconfig-") or k.startswith("_olav:") for k in r)
            for r in oc_result
        )
        if not has_oc:
            skipped_no_oc += 1
            continue

        if len(oc_result) == 1:
            new_data = json.dumps(oc_result[0])
        else:
            new_data = json.dumps(oc_result)

        if not dry_run:
            tbl = _base_table(con, "parsed_outputs")
            con.execute(
                f"UPDATE {tbl} SET parsed_data = ?::JSON WHERE device_name = ? AND command = ? AND snapshot_id = ?",
                [new_data, device_name, command, snapshot_id],
            )
        updated += 1

    logger.info(
        "parsed_outputs re-normalized: %d rows %s (skipped: %d no-platform, %d no-raw, %d parse-fail, %d no-oc-mapping)",
        updated,
        "(dry-run)" if dry_run else "updated",
        skipped_no_platform,
        skipped_no_raw,
        skipped_parse_fail,
        skipped_no_oc,
    )
    return updated


def rebuild_topology(con: duckdb.DuckDBPyConnection, dry_run: bool = False) -> int:
    from olav.core.topology_engine import extract_lldp_topology

    if not dry_run:
        tbl = _base_table(con, "topology_links")
        con.execute(f"DELETE FROM {tbl} WHERE discovery_protocol IN ('LLDP', 'CDP')")

    result = extract_lldp_topology(con)
    count = result.get("links_inserted", 0)
    logger.info(
        "topology_links rebuilt: %d LLDP/CDP links %s",
        count,
        "(dry-run)" if dry_run else "inserted",
    )
    return count


def rebuild_shared_contract_views(con: duckdb.DuckDBPyConnection, dry_run: bool = False) -> None:
    """Rebuild OpenConfig-aware summary views used by NL queries and dashboards.

    Delegates to ``olav.core.views.ensure_semantic_views`` which is the
    authoritative owner of all view DDLs (Phase 3 view ownership migration).
    """
    from olav.core.views import ensure_semantic_views

    if dry_run:
        logger.info("shared contract views rebuilt: dry-run only")
        return
    ensure_semantic_views(con)
    logger.info(
        "shared contract views rebuilt: v_interfaces / v_bgp_neighbors / v_topo_links_clean / v_l2_topology_summary / v_device_neighbors_summary"
    )


def refresh_summary_tables(con: duckdb.DuckDBPyConnection, dry_run: bool = False) -> None:
    """Refresh base summary tables from repaired views."""
    if dry_run:
        logger.info("summary tables refresh: dry-run only")
        return
    con.execute("DELETE FROM interfaces")
    con.execute("""
        INSERT INTO interfaces (device_name, interface, ip_address, status, description, snapshot_id)
        SELECT device_name, interface, ip_address, COALESCE(line_status, admin_status), NULL, snapshot_id
        FROM v_interfaces
    """)
    con.execute("DELETE FROM bgp_neighbors")
    con.execute("""
        INSERT INTO bgp_neighbors (device_name, neighbor_ip, neighbor_as, state, prefixes_received, snapshot_id)
        SELECT device_name, neighbor_ip, neighbor_as, state, prefixes_received, snapshot_id
        FROM v_bgp_neighbors
    """)
    logger.info("summary tables refreshed from repaired views")


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    from olav.core.config import MAIN_DB_PATH

    logger.info("Connecting to %s (dry_run=%s)", MAIN_DB_PATH, dry_run)
    con = duckdb.connect(str(MAIN_DB_PATH))

    try:
        reseed_yang_leaves(con)
        normalize_netconf_rows(con, dry_run=dry_run)
        rebuild_mapping_rules(con)
        renormalize_parsed_outputs(con, dry_run=dry_run)
        rebuild_shared_contract_views(con, dry_run=dry_run)
        refresh_summary_tables(con, dry_run=dry_run)
        rebuild_topology(con, dry_run=dry_run)
    finally:
        con.close()

    logger.info("Migration complete.")


if __name__ == "__main__":
    main()

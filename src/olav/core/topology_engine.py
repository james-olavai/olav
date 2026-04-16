"""Topology ETL — extract CDP/LLDP neighbours from parsed_outputs → topology_links.

Called by ``netops_init`` after snapshot ingestion:

    from olav.core.topology_engine import extract_lldp_topology
    with duckdb.connect(str(MAIN_DB_PATH)) as con:
        extract_lldp_topology(con)
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb as _duckdb

logger = logging.getLogger(__name__)

_CDP_COMMANDS = {"show cdp neighbors detail", "show cdp neighbors"}
_LLDP_COMMANDS = {"show lldp neighbors detail", "show lldp neighbors"}


def _make_link_id(src_dev: str, src_intf: str, dst_dev: str, dst_intf: str) -> str:
    """Deterministic bidirectional link ID — A→B and B→A produce the same ID."""
    pair_a = f"{src_dev.lower()}:{src_intf.lower()}"
    pair_b = f"{dst_dev.lower()}:{dst_intf.lower()}"
    canonical = "|".join(sorted([pair_a, pair_b]))
    return hashlib.md5(canonical.encode()).hexdigest()  # noqa: S324


def _normalise(val: str | None) -> str:
    return (val or "").strip()


def extract_lldp_topology(con: "_duckdb.DuckDBPyConnection") -> int:
    """Extract CDP/LLDP neighbour records from ``parsed_outputs`` into ``topology_links``.

    Args:
        con: Open (read-write) DuckDB connection that already has the ``netops``
             schema attached.

    Returns:
        Number of new rows inserted into ``topology_links``.
    """
    # Ensure topology_links table exists (may not have been created by IngestManager)
    try:
        from olav.platform.ingest_base import TableRegistry
        topo_tbl = TableRegistry.get("topology_links")
        if topo_tbl is not None:
            topo_tbl.ensure_schema(con)
        else:
            # Minimal DDL fallback if table not registered
            con.execute("CREATE SCHEMA IF NOT EXISTS netops")
            con.execute("""
                CREATE TABLE IF NOT EXISTS netops.topology_links (
                    link_id VARCHAR PRIMARY KEY,
                    source_device VARCHAR NOT NULL, source_interface VARCHAR NOT NULL,
                    destination_device VARCHAR NOT NULL, destination_interface VARCHAR NOT NULL,
                    discovery_protocol VARCHAR, link_type VARCHAR, link_status VARCHAR,
                    link_speed VARCHAR, first_seen TIMESTAMP NOT NULL, last_seen TIMESTAMP NOT NULL,
                    last_verified TIMESTAMP, status_changes INTEGER,
                    snapshot_id VARCHAR NOT NULL, platform VARCHAR
                )
            """)
    except Exception as exc:
        logger.warning("topology_engine: could not ensure topology_links table: %s", exc)

    query = """
        SELECT device_name, command, parsed_data, snapshot_id
        FROM   netops.parsed_outputs
        WHERE  command IN (
            'show cdp neighbors detail',
            'show cdp neighbors',
            'show lldp neighbors detail',
            'show lldp neighbors'
        )
        AND parsed_data IS NOT NULL
    """
    try:
        rows = con.execute(query).fetchall()
    except Exception as exc:
        logger.warning("topology_engine: could not query parsed_outputs: %s", exc)
        return 0

    now = datetime.utcnow().isoformat(timespec="seconds")
    inserted = 0

    for device_name, command, parsed_data, snapshot_id in rows:
        protocol = "CDP" if command in _CDP_COMMANDS else "LLDP"

        if isinstance(parsed_data, str):
            try:
                entries = json.loads(parsed_data)
            except json.JSONDecodeError:
                continue
        elif isinstance(parsed_data, list):
            entries = parsed_data
        else:
            continue

        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            # Both ntc-templates CDP and LLDP use the same field names
            src_dev = _normalise(device_name)
            src_intf = _normalise(
                entry.get("local_interface")
                or entry.get("LOCAL_INTERFACE")
            )
            dst_dev = _normalise(
                entry.get("NEIGHBOR_NAME")
                or entry.get("neighbor_name")
                or entry.get("NEIGHBOR")
                or entry.get("neighbor")
            )
            dst_intf = _normalise(
                entry.get("NEIGHBOR_INTERFACE")
                or entry.get("neighbor_interface")
                or entry.get("NEIGHBOR_PORT_ID")
                or entry.get("neighbor_port_id")
            )

            if not (src_dev and dst_dev) or src_dev == dst_dev:
                continue

            link_id = _make_link_id(src_dev, src_intf, dst_dev, dst_intf)

            try:
                con.execute(
                    """
                    INSERT OR IGNORE INTO netops.topology_links
                        (link_id, source_device, source_interface,
                         destination_device, destination_interface,
                         discovery_protocol, link_type, link_status,
                         first_seen, last_seen, snapshot_id)
                    VALUES (?, ?, ?, ?, ?, ?, 'L2', 'up', ?, ?, ?)
                    """,
                    [
                        link_id,
                        src_dev,
                        src_intf,
                        dst_dev,
                        dst_intf,
                        protocol,
                        now,
                        now,
                        snapshot_id or "unknown",
                    ],
                )
                inserted += 1
            except Exception as exc:
                logger.debug("topology_engine: insert failed for %s: %s", link_id, exc)

    # ── Raw fallback: extract links from raw_output_store for missing devices ──
    try:
        devices_with_links = set()
        for row in con.execute("SELECT DISTINCT source_device FROM netops.topology_links").fetchall():
            devices_with_links.add(row[0])

        all_devices = set()
        try:
            for row in con.execute("SELECT hostname FROM netops.devices").fetchall():
                all_devices.add(row[0])
        except Exception:
            pass

        missing = all_devices - devices_with_links
        if missing:
            logger.info("topology_engine: %d devices missing links, trying raw fallback: %s", len(missing), missing)
            raw_inserted = _extract_links_from_raw(con, missing, now)
            inserted += raw_inserted
    except Exception as exc:
        logger.debug("topology_engine: raw fallback failed (non-fatal): %s", exc)

    logger.info("topology_engine: inserted %d topology_links rows", inserted)
    return inserted


def _extract_links_from_raw(
    con: "_duckdb.DuckDBPyConnection", devices: set[str], now: str
) -> int:
    """Extract neighbor links from raw CLI text when parsed_outputs is missing."""
    import re

    inserted = 0
    for device in devices:
        for cmd_pattern, protocol in [
            ("show lldp neighbor%", "LLDP"),
            ("show cdp neighbor%", "CDP"),
        ]:
            try:
                rows = con.execute(
                    "SELECT raw_output, snapshot_id FROM netops.raw_output_store "
                    "WHERE device_name = ? AND command LIKE ?",
                    [device, cmd_pattern],
                ).fetchall()
            except Exception:
                continue

            for raw_output, snapshot_id in rows:
                if not raw_output or len(raw_output) < 50:
                    continue
                links = _parse_neighbors_from_raw(raw_output, device, protocol)
                for src_intf, dst_dev, dst_intf in links:
                    link_id = _make_link_id(device, src_intf, dst_dev, dst_intf)
                    try:
                        con.execute(
                            """
                            INSERT OR IGNORE INTO netops.topology_links
                                (link_id, source_device, source_interface,
                                 destination_device, destination_interface,
                                 discovery_protocol, link_type, link_status,
                                 first_seen, last_seen, snapshot_id)
                            VALUES (?, ?, ?, ?, ?, ?, 'L2', 'up', ?, ?, ?)
                            """,
                            [link_id, device, src_intf, dst_dev, dst_intf,
                             protocol, now, now, snapshot_id or "unknown"],
                        )
                        inserted += 1
                    except Exception as exc:
                        logger.debug("raw fallback insert failed: %s", exc)

    if inserted:
        logger.info("topology_engine: raw fallback extracted %d additional links", inserted)
    return inserted


def _parse_neighbors_from_raw(
    raw_text: str, source_device: str, protocol: str
) -> list[tuple[str, str, str]]:
    """Regex-based neighbor extraction from raw CLI output.

    Returns list of (source_interface, dest_device, dest_interface).
    """
    import re
    results = []
    lines = raw_text.strip().split("\n")

    if protocol == "LLDP":
        # Junos LLDP: "ge-0/0/2  -  50:00:00:03:00:02  to_R1_Gi2  R3.local"
        # Columns: Local Interface, Parent Interface, Chassis Id, Port info, System Name
        for line in lines:
            parts = line.split()
            if len(parts) >= 5 and "/" in parts[0]:
                local_intf = parts[0]
                remote_port = parts[-2]
                remote_name = parts[-1]
                if remote_name and remote_name != "-":
                    results.append((local_intf, remote_name, remote_port))
            # IOS LLDP: various formats
            elif len(parts) >= 4:
                # Try "Et0/0  R3  Et0/1  120" pattern
                m = re.match(r'^(\S+)\s+(\S+)\s+(\S+)\s+\d+', line)
                if m and ("/" in m.group(1) or m.group(1).startswith("Gi") or m.group(1).startswith("Et")):
                    results.append((m.group(1), m.group(2), m.group(3)))

    elif protocol == "CDP":
        # IOS CDP detail: "Device ID: R4\n  Interface: Gi0/2,  Port ID (outgoing port): Et0/0"
        device_id = None
        local_intf = None
        for line in lines:
            m_dev = re.search(r'Device ID:\s*(\S+)', line)
            if m_dev:
                device_id = m_dev.group(1)
                local_intf = None
                continue
            m_intf = re.search(r'Interface:\s*(\S+),\s*Port ID.*?:\s*(\S+)', line)
            if m_intf and device_id:
                results.append((m_intf.group(1).rstrip(","), device_id, m_intf.group(2)))
                device_id = None

    return results

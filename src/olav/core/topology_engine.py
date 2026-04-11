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

    logger.info("topology_engine: inserted %d topology_links rows", inserted)
    return inserted

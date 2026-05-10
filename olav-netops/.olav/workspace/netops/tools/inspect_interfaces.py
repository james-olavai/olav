"""inspect_interfaces @tool — per-interface IP / status lookup.

Closes the inspector data gap exposed by the 2026-05-11 freeform_cli
sim→lab E2E test (commit `015a827`): sim could not ground next-hop
IPs for static routes / OSPF / etc. because no inspector returns
per-link interface IP addressing.

Reads ``netops.v_show_ip_interface_brief_auto`` (latest snapshot per
device) — the same view the CAB stack already relies on for
pre_check / post_check generation.  Filters by hostname; omits
"unassigned" interfaces by default to keep the result focused.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
from langchain_core.tools import tool


def _db_path() -> Path:
    """Resolve main.duckdb the same way the rest of the stack does."""
    # Prefer current working directory (where the CLI is invoked).
    cwd_db = Path.cwd() / ".olav" / "databases" / "main.duckdb"
    if cwd_db.exists():
        return cwd_db
    # Fall back to OLAV_BASE_PATH if set.
    import os
    base = os.environ.get("OLAV_BASE_PATH")
    if base:
        p = Path(base) / "databases" / "main.duckdb"
        if p.exists():
            return p
    return cwd_db  # let DuckDB raise the missing-file error


@tool
def inspect_interfaces(
    devices: list[str],
    include_unassigned: bool = False,
) -> dict[str, Any]:
    """
    Get per-interface IP / status / proto for the named devices.

    Use this when planning changes that need a specific interface IP
    (e.g. static route next-hop, ACL apply target, OSPF area
    interface).  Returns the most recent snapshot's data per device.

    Args:
        devices: List of hostnames.  E.g. ``["R1", "R3"]``.  An
            empty list returns interfaces for every device with
            data (discovery mode).
        include_unassigned: If False (default), skip interfaces
            whose ``ip_address`` is ``"unassigned"`` or empty —
            keeps the result focused on routable interfaces.  Set
            True if you need full inventory including unconfigured
            ports.

    Returns:
        ``{
            "found": {
                hostname: [
                    {"interface": "Ethernet0/0",
                     "ip_address": "10.1.13.3",
                     "status": "up", "proto": "up"},
                    ...
                ],
                ...
            },
            "snapshot_ids": {hostname: snapshot_id},
            "unknown_devices": [hostname, ...],   # no rows in view
        }``.

    Example:
        >>> inspect_interfaces(["R3"])
        {
            "found": {
                "R3": [
                    {"interface": "Ethernet0/0", "ip_address": "10.1.13.3",
                     "status": "up", "proto": "up"},
                    {"interface": "Loopback0", "ip_address": "3.3.3.3",
                     "status": "up", "proto": "up"},
                    ...
                ]
            },
            "snapshot_ids": {"R3": "snap_20260430_045409_f9b5d7"},
            "unknown_devices": [],
        }
    """
    db = _db_path()
    if not db.exists():
        return {
            "found": {},
            "snapshot_ids": {},
            "unknown_devices": list(devices),
            "error": f"main.duckdb not found at {db}",
        }

    found: dict[str, list[dict[str, Any]]] = {}
    snapshot_ids: dict[str, str] = {}
    unknown_devices: list[str] = []

    with duckdb.connect(str(db), read_only=True) as con:
        # Discovery mode: enumerate every device with rows
        if not devices:
            rows = con.execute("""
                SELECT DISTINCT device_name FROM netops.v_show_ip_interface_brief_auto
                ORDER BY device_name
            """).fetchall()
            target_devices = [r[0] for r in rows]
        else:
            target_devices = list(devices)

        for d in target_devices:
            # Try Cisco IOS view first (v_show_ip_interface_brief_auto),
            # fall back to Junos view (v_show_interfaces_terse_auto).
            # The IOS view has columns (interface, ip_address, status,
            # proto); Junos terse has (interface, admin_state,
            # link_state, proto, ip_address, remote) and only emits a
            # row per logical unit (e.g. ge-0/0/0.0) when ip is set.
            ios_latest = con.execute("""
                SELECT MAX(snapshot_id) FROM netops.v_show_ip_interface_brief_auto
                WHERE device_name = ?
            """, [d]).fetchone()
            jun_latest = con.execute("""
                SELECT MAX(snapshot_id) FROM netops.v_show_interfaces_terse_auto
                WHERE device_name = ?
            """, [d]).fetchone()

            ios_snap = ios_latest[0] if ios_latest else None
            jun_snap = jun_latest[0] if jun_latest else None

            if not ios_snap and not jun_snap:
                unknown_devices.append(d)
                continue

            entries: list[dict[str, Any]] = []
            # Pick the platform that actually has data.  Prefer the
            # one with rows; if both have rows, prefer ios for IOS
            # boxes and junos for Junos boxes (sortable on snapshot
            # recency as a tiebreak).
            if ios_snap:
                snapshot_ids[d] = ios_snap
                rows = con.execute("""
                    SELECT interface, ip_address, status, proto
                    FROM netops.v_show_ip_interface_brief_auto
                    WHERE device_name = ? AND snapshot_id = ?
                    ORDER BY interface
                """, [d, ios_snap]).fetchall()
                for intf, ip, status, proto in rows:
                    if not include_unassigned:
                        if not ip or str(ip).lower() in ("unassigned", "none", ""):
                            continue
                    entries.append({
                        "interface": intf,
                        "ip_address": ip,
                        "status": status,
                        "proto": proto,
                    })
            if not entries and jun_snap:
                snapshot_ids[d] = jun_snap
                rows = con.execute("""
                    SELECT interface, ip_address, link_state, proto
                    FROM netops.v_show_interfaces_terse_auto
                    WHERE device_name = ? AND snapshot_id = ?
                    ORDER BY interface
                """, [d, jun_snap]).fetchall()
                for intf, ip, link_state, proto in rows:
                    if not include_unassigned:
                        if not ip or str(ip).strip() == "":
                            continue
                    entries.append({
                        "interface": intf,
                        "ip_address": ip,
                        "status": link_state,
                        "proto": proto,
                    })

            if not entries:
                unknown_devices.append(d)
            else:
                found[d] = entries

    return {
        "found": found,
        "snapshot_ids": snapshot_ids,
        "unknown_devices": unknown_devices,
    }

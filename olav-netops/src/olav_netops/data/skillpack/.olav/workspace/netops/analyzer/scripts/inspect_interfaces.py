#!/usr/bin/env python3
"""inspect_interfaces — per-interface IP / status lookup for the analyzer.

Migrated from @tool (netops/tools/inspect_interfaces.py) to script (ADR-0007
rev ~301): stateless DuckDB read — no persistent state, no audit row.

Reads ``netops.v_show_ip_interface_brief_auto`` (latest snapshot per device)
with Junos terse fallback via ``netops.v_show_interfaces_terse_auto``.

Accepts JSON on stdin:
  {"devices": ["R1", "R3"], "include_unassigned": false}
Pass devices=[] for discovery mode (all devices with interface data).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import duckdb


def _db_path() -> Path:
    cwd_db = Path.cwd() / ".olav" / "databases" / "main.duckdb"
    if cwd_db.exists():
        return cwd_db
    base = os.environ.get("OLAV_BASE_PATH")
    if base:
        p = Path(base) / "databases" / "main.duckdb"
        if p.exists():
            return p
    return cwd_db


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
            "unknown_devices": [hostname, ...],
        }``.
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
        if not devices:
            rows = con.execute("""
                SELECT DISTINCT device_name
                FROM netops.v_show_ip_interface_brief_auto
                ORDER BY device_name
            """).fetchall()
            target_devices = [r[0] for r in rows]
        else:
            target_devices = list(devices)

        for d in target_devices:
            ios_latest = con.execute("""
                SELECT MAX(snapshot_id)
                FROM netops.v_show_ip_interface_brief_auto
                WHERE device_name = ?
            """, [d]).fetchone()
            jun_latest = con.execute("""
                SELECT MAX(snapshot_id)
                FROM netops.v_show_interfaces_terse_auto
                WHERE device_name = ?
            """, [d]).fetchone()

            ios_snap = ios_latest[0] if ios_latest else None
            jun_snap = jun_latest[0] if jun_latest else None

            if not ios_snap and not jun_snap:
                unknown_devices.append(d)
                continue

            entries: list[dict[str, Any]] = []
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


if __name__ == "__main__":
    import json as _json
    import sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = inspect_interfaces(**_args)
    print(_json.dumps(result, default=str))

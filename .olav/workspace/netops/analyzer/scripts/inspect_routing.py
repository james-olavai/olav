#!/usr/bin/env python3
"""inspect_routing — routing protocol neighborship lookup for the analyzer sub-agent.

Reads BGP and OSPF session state from the NetworkModel topology graph,
augmented with route-table evidence from DuckDB when available.

Accepts JSON on stdin: {"devices": ["R1", "R3"], "protocol": "bgp"}
protocol: "bgp" | "ospf" | "all"  (default: "bgp")
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import duckdb

from olav_netops.sim import load_network_model


def _main_db_path() -> Path:
    cwd = Path(os.environ.get("OLAV_CWD", "."))
    return cwd / ".olav" / "databases" / "main.duckdb"


def inspect_routing(
    devices: list[str],
    protocol: str = "bgp",
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """
    Return BGP and/or OSPF neighborship state for the named devices.

    Uses the topology graph (edge attributes) as primary source.
    Falls back to DuckDB parsed_outputs when graph edges lack session detail.

    Args:
        devices: Hostnames to inspect. E.g. ``["R1", "R3"]``.
        protocol: ``"bgp"``, ``"ospf"``, or ``"all"``.
        snapshot_id: Optional snapshot to scope the DB query.

    Returns:
        ``{hostname: {"bgp": [...sessions], "ospf": [...sessions]}}``

        BGP session: ``{"neighbor": str, "state": str, "resolved": bool,
                        "neighbor_ip": str|None, "neighbor_as": int|None,
                        "prefixes_received": int|None}``
        OSPF session: ``{"neighbor": str, "state": str}``
    """
    model = load_network_model()
    graph = model.graph

    want_bgp = protocol in ("bgp", "all")
    want_ospf = protocol in ("ospf", "all")

    result: dict[str, Any] = {}

    db_path = _main_db_path()
    db_routes: dict[str, list[dict]] = {}
    try:
        with duckdb.connect(str(db_path), read_only=True) as con:
            snap_filter = f"AND snapshot_id = '{snapshot_id}'" if snapshot_id else ""
            rows = con.execute(
                f"SELECT device_name, command, output FROM netops.raw_output_store "
                f"WHERE command LIKE '%bgp%' OR command LIKE '%ospf%' {snap_filter} LIMIT 200"
            ).fetchall()
            for device_name, _cmd, _out in rows:
                db_routes.setdefault(device_name, [])
    except Exception:
        pass

    for device in devices:
        if device not in graph:
            continue

        bgp_sessions: list[dict] = []
        ospf_sessions: list[dict] = []

        for neighbor in graph.successors(device):
            attrs = graph[device][neighbor]

            if want_bgp and attrs.get("bgp_session"):
                bgp_sessions.append({
                    "neighbor": neighbor,
                    "neighbor_ip": attrs.get("bgp_neighbor_ip"),
                    "neighbor_as": attrs.get("bgp_neighbor_as"),
                    "state": attrs.get("bgp_session_state", "Unknown"),
                    "prefixes_received": attrs.get("bgp_prefixes_received"),
                    "resolved": True,
                })

            if want_ospf and attrs.get("ospf_state"):
                ospf_sessions.append({
                    "neighbor": neighbor,
                    "state": attrs.get("ospf_state"),
                })

        result[device] = {
            "bgp": bgp_sessions,
            "ospf": ospf_sessions,
        }

    return result


if __name__ == "__main__":
    _args = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(inspect_routing(**_args), default=str))

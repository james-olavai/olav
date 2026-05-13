"""Python-only inspector functions used by staged_fill.

These are PYTHON callables, NOT LangChain @tools. The staged-fill flow
calls them directly (no LLM in the loop) — guarantees facts come from
the DB, not from LLM hallucination.

Schema-aligned with FactsEnvelope so the staged-fill prompts can ask
the LLM to copy verbatim.
"""
from __future__ import annotations

import json
from typing import Any


def inspect_devices(names: list[str]) -> dict[str, Any]:
    """Return {"devices": [{name, platform, local_as, loopback, interfaces}, ...]}."""
    import duckdb
    from olav.core.config import MAIN_DB_PATH

    if not names:
        return {"devices": []}
    con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
    try:
        out: list[dict] = []
        for n in names:
            row = con.execute(
                "SELECT hostname, platform, metadata FROM netops.devices WHERE hostname = ?",
                [n],
            ).fetchone()
            if not row:
                continue
            md = (json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})) or {}
            asn_row = con.execute(
                "SELECT local_as FROM netops.v_show_ip_bgp_summary_auto "
                "WHERE device_name = ? LIMIT 1",
                [n],
            ).fetchone()
            out.append({
                "name": n,
                "platform": row[1],
                "loopback": md.get("loopback_ip"),
                "local_as": int(asn_row[0]) if asn_row and asn_row[0] else None,
                "interfaces": [],
            })
        return {"devices": out}
    finally:
        con.close()


def inspect_topology(names: list[str]) -> dict[str, Any]:
    """Return {"topology_edges": [...]} for L2 links among the named devices."""
    import duckdb
    from olav.core.config import MAIN_DB_PATH

    if not names:
        return {"topology_edges": []}
    con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
    try:
        placeholders = ",".join("?" * len(names))
        rows = con.execute(
            f"SELECT source_device, source_interface, destination_device, "
            f"destination_interface, discovery_protocol "
            f"FROM netops.v_l2_links_auto "
            f"WHERE source_device IN ({placeholders}) "
            f"AND destination_device IN ({placeholders})",
            names * 2,
        ).fetchall()
        return {
            "topology_edges": [
                {"source_device": r[0], "source_interface": r[1],
                 "destination_device": r[2], "destination_interface": r[3],
                 "discovery_protocol": r[4]}
                for r in rows
            ],
        }
    finally:
        con.close()

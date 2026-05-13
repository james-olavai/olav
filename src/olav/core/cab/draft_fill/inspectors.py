"""Python-only inspector functions used by staged_fill.

These are PYTHON callables, NOT LangChain @tools. The staged-fill flow
calls them directly (no LLM in the loop) — guarantees facts come from
the DB, not from LLM hallucination.

Cross-resolve port (2026-05-13): inspect_devices applies the same
LLDP-peer cross-resolution logic ``tcf_writer._db_facts`` has for
Junos devices that don't show in the Cisco-style
``v_show_ip_bgp_summary_auto`` view. Without this, junos local_as +
loopback come back null (verified in-vivo with R1).

Topology dedup (2026-05-13): inspect_topology applies the same
LLDP-description guard as ``lab/topology._dedupe_bidirectional`` —
drops rows where the remote interface name is a description string
the far-side LLDP advertised (e.g. R1 reporting peer as "to_R1_Gi2"
instead of "Ethernet0/0"). Single canonical edge per physical link.
"""
from __future__ import annotations

import json
from typing import Any


def inspect_devices(names: list[str]) -> dict[str, Any]:
    """Return {"devices": [...]} with cross-resolved junos ASN + loopback."""
    import duckdb
    from olav.core.config import MAIN_DB_PATH

    if not names:
        return {"devices": []}

    facts: dict[str, dict[str, Any]] = {
        n: {"name": n, "platform": None, "local_as": None,
             "loopback": None, "interfaces": []}
        for n in names
    }

    try:
        con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
    except Exception:
        return {"devices": list(facts.values())}

    try:
        placeholders = ",".join("?" * len(names))

        # 1. platform + metadata.loopback_ip from netops.devices
        for hostname, platform, metadata in con.execute(
            f"SELECT hostname, platform, metadata FROM netops.devices "
            f"WHERE hostname IN ({placeholders})",
            names,
        ).fetchall():
            if hostname not in facts:
                continue
            facts[hostname]["platform"] = platform
            if metadata:
                try:
                    md = json.loads(metadata) if isinstance(metadata, str) else (metadata or {})
                    if isinstance(md, dict) and md.get("loopback_ip"):
                        facts[hostname]["loopback"] = md["loopback_ip"]
                except (json.JSONDecodeError, TypeError):
                    pass

        # 2. router_id + local_as from BGP summary (Cisco-style view)
        for hostname, router_id, local_as in con.execute(
            f"SELECT device_name, router_id, local_as "
            f"FROM netops.v_show_ip_bgp_summary_auto "
            f"WHERE device_name IN ({placeholders})",
            names,
        ).fetchall():
            if hostname not in facts:
                continue
            if facts[hostname]["local_as"] is None and local_as is not None:
                try:
                    facts[hostname]["local_as"] = int(local_as)
                except (TypeError, ValueError):
                    pass
            if facts[hostname]["loopback"] is None and router_id:
                facts[hostname]["loopback"] = router_id

        # 3. Cross-resolve: junos device A has its loopback known (from
        #    step 1) but no row in BGP summary view. Look across ALL
        #    BGP summary rows for one whose `bgp_neighbor` matches A's
        #    loopback — its `neighbor_as` is A's local_as.
        known_loopbacks = {
            f["loopback"]: n for n, f in facts.items() if f.get("loopback")
        }
        if known_loopbacks:
            for _, neighbor, neighbor_as in con.execute(
                "SELECT device_name, bgp_neighbor, neighbor_as "
                "FROM netops.v_show_ip_bgp_summary_auto"
            ).fetchall():
                target = known_loopbacks.get(neighbor)
                if target and facts[target]["local_as"] is None:
                    try:
                        facts[target]["local_as"] = int(neighbor_as)
                    except (TypeError, ValueError):
                        pass

        # 4. Heuristic: target has neither loopback nor ASN; a peer in
        #    scope has exactly ONE neighbor in its BGP table → that
        #    neighbor's IP is our loopback, neighbor_as is our ASN.
        for target in names:
            if facts[target]["loopback"] is not None and facts[target]["local_as"] is not None:
                continue
            for other in names:
                if other == target or facts[other]["local_as"] is None:
                    continue
                rows = con.execute(
                    "SELECT bgp_neighbor, neighbor_as "
                    "FROM netops.v_show_ip_bgp_summary_auto "
                    "WHERE device_name = ?",
                    [other],
                ).fetchall()
                if len(rows) == 1:
                    n, na = rows[0]
                    if facts[target]["loopback"] is None and n:
                        facts[target]["loopback"] = n
                    if facts[target]["local_as"] is None:
                        try:
                            facts[target]["local_as"] = int(na)
                        except (TypeError, ValueError):
                            pass
    finally:
        con.close()

    return {"devices": list(facts.values())}


def inspect_topology(names: list[str]) -> dict[str, Any]:
    """Return {"topology_edges": [...]} with LLDP-description dedup."""
    import duckdb
    from olav.core.config import MAIN_DB_PATH

    if not names:
        return {"topology_edges": []}

    try:
        con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
    except Exception:
        return {"topology_edges": []}

    try:
        placeholders = ",".join("?" * len(names))
        raw_rows = con.execute(
            f"SELECT source_device, source_interface, destination_device, "
            f"destination_interface, discovery_protocol "
            f"FROM netops.v_l2_links_auto "
            f"WHERE source_device IN ({placeholders}) "
            f"AND destination_device IN ({placeholders})",
            names * 2,
        ).fetchall()
    finally:
        con.close()

    # LLDP-description guard: keep only rows whose (dst_dev, dst_intf)
    # appears as the (src_dev, src_intf) of ANOTHER row — i.e. the dst
    # interface IS a real port on dst. Strips description strings
    # (e.g. "to_R1_Gi2") that LLDP advertises as the remote port name.
    rows = [(r[0], r[1], r[2], r[3], r[4]) for r in raw_rows]
    real_src = {(d, i) for d, i, _, _, _ in rows}
    filtered = [r for r in rows if (r[2], r[3]) in real_src]
    if not filtered:
        filtered = list(rows)

    # Canonical dedup: collapse (A,iA,B,iB) and (B,iB,A,iA) to one.
    seen: set[tuple[str, str, str, str]] = set()
    canonical: list[tuple] = []
    for r in filtered:
        a, b = (r[0], r[1]), (r[2], r[3])
        key = (*a, *b) if a <= b else (*b, *a)
        if key in seen:
            continue
        seen.add(key)
        canonical.append(r)

    return {
        "topology_edges": [
            {"source_device": r[0], "source_interface": r[1],
             "destination_device": r[2], "destination_interface": r[3],
             "discovery_protocol": r[4]}
            for r in canonical
        ],
    }

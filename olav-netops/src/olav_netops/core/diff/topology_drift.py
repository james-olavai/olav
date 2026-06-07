"""Topology drift helper — detect physical link state changes
between snapshots.

Compares ``topology_links`` to find links that went down, came up,
or changed status. Called by ``inspect_drift_topology`` (per ADR-0007
R91); not registered as a direct MCP tool.
"""

from __future__ import annotations

import duckdb

from olav.core.config import MAIN_DB_PATH


def _normalize_device_name(name: str) -> str:
    """Normalize device name for comparison."""
    return name.lower().strip() if name else ""


def _create_edge_key(source: str, dest: str) -> str:
    """Create normalized bidirectional edge key."""
    s = _normalize_device_name(source)
    d = _normalize_device_name(dest)
    return "|".join(sorted([s, d])) if s and d else ""


def _get_topology_links(snapshot_id: str) -> dict[str, dict]:
    """Get topology links for a snapshot, indexed by edge key."""
    with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
        try:
            result = conn.execute(
                """
                SELECT source_device, source_interface, dest_device, dest_interface,
                       discovery_protocol, link_type, link_status
                FROM topology_links
                WHERE snapshot_id = ?
            """,
                [snapshot_id],
            ).fetchall()

            links = {}
            for r in result:
                edge_key = _create_edge_key(r[0], r[2])
                if edge_key:
                    links[edge_key] = {
                        "source": r[0],
                        "src_int": r[1],
                        "dest": r[2],
                        "dst_int": r[3],
                        "protocol": r[4],
                        "link_type": r[5],
                        "link_status": r[6],
                    }
            return links
        except Exception:
            return {}


def diff_topology_drift(snapshot_id_1: str, snapshot_id_2: str) -> dict:
    """Detect physical topology changes between two snapshots.

    Identifies:
    * Links that went DOWN (in T1 but not T2)
    * Links that came UP (in T2 but not T1)
    * Status changes (in both, but ``link_status`` differs)
    """
    try:
        links_t1 = _get_topology_links(snapshot_id_1)
        links_t2 = _get_topology_links(snapshot_id_2)

        links_down = [link for k, link in links_t1.items() if k not in links_t2]
        links_up = [link for k, link in links_t2.items() if k not in links_t1]

        status_changes = []
        for edge_key, link_t1 in links_t1.items():
            link_t2 = links_t2.get(edge_key)
            if link_t2 is None:
                continue
            if link_t1.get("link_status") != link_t2.get("link_status"):
                status_changes.append(
                    {
                        "source": link_t1["source"],
                        "src_int": link_t1["src_int"],
                        "dest": link_t1["dest"],
                        "dst_int": link_t1["dst_int"],
                        "old_status": link_t1.get("link_status"),
                        "new_status": link_t2.get("link_status"),
                    }
                )

        total = len(links_down) + len(links_up) + len(status_changes)
        return {
            "status": "success",
            "links_down": links_down,
            "links_up": links_up,
            "status_changes": status_changes,
            "total_changes": total,
            "message": f"Found {total} topology changes",
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

"""Routing drift helper — detect routing changes between snapshots.

Compares routing tables to find:
* Lost prefixes (reachable in T1, missing in T2)
* Next-hop path shifts (same prefix, different next_hop)
* BGP AS_PATH changes (path selection changes)

Called by ``inspect_drift_routing`` (per ADR-0007 R91); not registered
as a direct MCP tool.
"""

from __future__ import annotations

import duckdb

from olav.core.config import MAIN_DB_PATH


# Max changes to return (prevent context overflow)
MAX_CHANGES = 20


def _find_lost_routes(snapshot_1: str, snapshot_2: str, device: str | None) -> list[str]:
    """Find prefixes that existed in T1 but not in T2."""
    with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
        if device:
            query = """
                SELECT DISTINCT network || '/' || mask as prefix
                FROM routes
                WHERE snapshot_id = ? AND device_name = ?
                EXCEPT
                SELECT DISTINCT network || '/' || mask as prefix
                FROM routes
                WHERE snapshot_id = ? AND device_name = ?
            """
            result = conn.execute(query, [snapshot_1, device, snapshot_2, device]).fetchall()
        else:
            query = """
                SELECT DISTINCT network || '/' || mask as prefix
                FROM routes
                WHERE snapshot_id = ?
                EXCEPT
                SELECT DISTINCT network || '/' || mask as prefix
                FROM routes
                WHERE snapshot_id = ?
            """
            result = conn.execute(query, [snapshot_1, snapshot_2]).fetchall()

        return [r[0] for r in result]


def _find_next_hop_shifts(snapshot_1: str, snapshot_2: str, device: str | None) -> list[dict]:
    """Find routes where next_hop changed."""
    with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
        if device:
            query = """
                SELECT t1.network, t1.mask, t1.next_hop as old_hop, t2.next_hop as new_hop
                FROM routes t1
                LEFT JOIN routes t2 ON t1.device_name = t2.device_name 
                    AND t1.network = t2.network AND t1.mask = t2.mask
                WHERE t1.snapshot_id = ? AND t2.snapshot_id = ?
                    AND t1.device_name = ?
                    AND t1.next_hop != COALESCE(t2.next_hop, '')
            """
            result = conn.execute(query, [snapshot_1, snapshot_2, device]).fetchall()
        else:
            query = """
                SELECT t1.device_name, t1.network, t1.mask, t1.next_hop as old_hop, t2.next_hop as new_hop
                FROM routes t1
                LEFT JOIN routes t2 ON t1.device_name = t2.device_name 
                    AND t1.network = t2.network AND t1.mask = t2.mask
                WHERE t1.snapshot_id = ? AND t2.snapshot_id = ?
                    AND t1.next_hop != COALESCE(t2.next_hop, '')
            """
            result = conn.execute(query, [snapshot_1, snapshot_2]).fetchall()

        shifts = []
        for r in result:
            shifts.append(
                {
                    "network": f"{r[1]}/{r[2]}" if len(r) > 2 else r[1],
                    "old_next_hop": r[2] if len(r) > 2 else r[1],
                    "new_next_hop": r[3] if len(r) > 2 else r[2],
                }
            )
            if len(r) > 3:
                shifts[-1]["device_name"] = r[0]

        return shifts[:MAX_CHANGES]


def _find_bgp_as_path_changes(snapshot_1: str, snapshot_2: str, device: str | None) -> list[dict]:
    """Find BGP routes where AS_PATH changed."""
    with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
        if device:
            query = """
                SELECT t1.network, t1.as_path as old_path, t2.as_path as new_path
                FROM bgp_routes t1
                LEFT JOIN bgp_routes t2 ON t1.device_name = t2.device_name 
                    AND t1.network = t2.network
                WHERE t1.snapshot_id = ? AND t2.snapshot_id = ?
                    AND t1.device_name = ?
                    AND t1.as_path != COALESCE(t2.as_path, '')
            """
            result = conn.execute(query, [snapshot_1, snapshot_2, device]).fetchall()
        else:
            query = """
                SELECT t1.device_name, t1.network, t1.as_path as old_path, t2.as_path as new_path
                FROM bgp_routes t1
                LEFT JOIN bgp_routes t2 ON t1.device_name = t2.device_name 
                    AND t1.network = t2.network
                WHERE t1.snapshot_id = ? AND t2.snapshot_id = ?
                    AND t1.as_path != COALESCE(t2.as_path, '')
            """
            result = conn.execute(query, [snapshot_1, snapshot_2]).fetchall()

        changes = []
        for r in result:
            changes.append(
                {
                    "network": r[1],
                    "old_path": r[1] if len(r) > 2 else r[1],
                    "new_path": r[2] if len(r) > 2 else r[2],
                }
            )
            if len(r) > 2:
                changes[-1]["device_name"] = r[0]

        return changes[:MAX_CHANGES]


def diff_routing_drift(
    snapshot_id_1: str,
    snapshot_id_2: str,
    device_name: str | None = None,
) -> dict:
    """Detect routing changes between two snapshots.

    Identifies lost prefixes, next-hop path shifts, and BGP
    AS_PATH changes. Limited to ``MAX_CHANGES`` (20) per category
    to prevent context overflow.
    """
    try:
        lost = _find_lost_routes(snapshot_id_1, snapshot_id_2, device_name)
        shifts = _find_next_hop_shifts(snapshot_id_1, snapshot_id_2, device_name)
        bgp_changes = _find_bgp_as_path_changes(snapshot_id_1, snapshot_id_2, device_name)

        total = len(lost) + len(shifts) + len(bgp_changes)
        summary = None
        if total > MAX_CHANGES:
            summary = (
                f"And {total - MAX_CHANGES} other changes not shown "
                f"(limited to {MAX_CHANGES})"
            )

        return {
            "status": "success",
            "device_name": device_name,
            "lost_destinations": lost[:MAX_CHANGES],
            "path_shifts": shifts,
            "bgp_as_path_changes": bgp_changes,
            "total_changes": total,
            "summary": summary,
            "message": f"Found {total} routing changes",
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

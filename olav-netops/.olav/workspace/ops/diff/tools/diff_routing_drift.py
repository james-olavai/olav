#!/usr/bin/env python3
"""
Routing Drift Tool - Detect routing changes between snapshots.

Compares routing tables to find:
- Lost prefixes (reachable in T1, missing in T2)
- Next-hop path shifts (same prefix, different next_hop)
- BGP AS_PATH changes (path selection changes)

Limited to ~20 significant changes to prevent context overflow.

Usage:
    diff_routing_drift(snapshot_id_1="20260226_100000", snapshot_id_2="20260226_120000", device_name="R1")
"""

import json
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


def _find_project_root() -> Path:
    """Locate project root."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

import duckdb

from olav.core.config import MAIN_DB_PATH


class RoutingDriftInput(BaseModel):
    """Input for routing drift detection."""

    snapshot_id_1: str = Field(..., description="Baseline/Before snapshot ID")
    snapshot_id_2: str = Field(..., description="Target/After snapshot ID")
    device_name: str | None = Field(default=None, description="Filter by device name")


class RoutingDriftOutput(BaseModel):
    """Output from routing drift detection."""

    status: str = Field(..., description="success | error")
    device_name: str | None = Field(default=None, description="Device analyzed")
    lost_destinations: list[str] = Field(
        default_factory=list, description="Prefixes now unreachable"
    )
    path_shifts: list[dict] = Field(default_factory=list, description="Next-hop changes")
    bgp_as_path_changes: list[dict] = Field(default_factory=list, description="BGP path changes")
    total_changes: int = Field(default=0, description="Total number of changes")
    summary: str | None = Field(default=None, description="Summary if changes exceed limit")
    message: str | None = Field(default=None, description="Additional info")
    error: str | None = Field(default=None, description="Error message if status=error")


# Max changes to return (prevent context overflow)
MAX_CHANGES = 20


def _find_lost_routes(snapshot_1: str, snapshot_2: str, device: str | None) -> list[str]:
    """Find prefixes that existed in T1 but not in T2 (queries v_routes_auto)."""
    with duckdb.connect(str(MAIN_DB_PATH)) as conn:
        if device:
            query = """
                SELECT DISTINCT network AS prefix
                FROM v_routes_auto
                WHERE snapshot_id = ? AND device_name = ?
                EXCEPT
                SELECT DISTINCT network AS prefix
                FROM v_routes_auto
                WHERE snapshot_id = ? AND device_name = ?
            """
            result = conn.execute(query, [snapshot_1, device, snapshot_2, device]).fetchall()
        else:
            query = """
                SELECT DISTINCT network AS prefix
                FROM v_routes_auto
                WHERE snapshot_id = ?
                EXCEPT
                SELECT DISTINCT network AS prefix
                FROM v_routes_auto
                WHERE snapshot_id = ?
            """
            result = conn.execute(query, [snapshot_1, snapshot_2]).fetchall()

        return [r[0] for r in result]


def _find_next_hop_shifts(snapshot_1: str, snapshot_2: str, device: str | None) -> list[dict]:
    """Find routes where next_hop changed (queries v_routes_auto)."""
    with duckdb.connect(str(MAIN_DB_PATH)) as conn:
        if device:
            query = """
                SELECT t1.network, t1.next_hop AS old_hop, t2.next_hop AS new_hop
                FROM v_routes_auto t1
                LEFT JOIN v_routes_auto t2
                    ON t1.device_name = t2.device_name AND t1.network = t2.network
                WHERE t1.snapshot_id = ? AND t2.snapshot_id = ?
                    AND t1.device_name = ?
                    AND t1.next_hop != COALESCE(t2.next_hop, '')
            """
            result = conn.execute(query, [snapshot_1, snapshot_2, device]).fetchall()
            shifts = [{"network": r[0], "old_next_hop": r[1], "new_next_hop": r[2]} for r in result]
        else:
            query = """
                SELECT t1.device_name, t1.network, t1.next_hop AS old_hop, t2.next_hop AS new_hop
                FROM v_routes_auto t1
                LEFT JOIN v_routes_auto t2
                    ON t1.device_name = t2.device_name AND t1.network = t2.network
                WHERE t1.snapshot_id = ? AND t2.snapshot_id = ?
                    AND t1.next_hop != COALESCE(t2.next_hop, '')
            """
            result = conn.execute(query, [snapshot_1, snapshot_2]).fetchall()
            shifts = [{
                "device_name": r[0], "network": r[1],
                "old_next_hop": r[2], "new_next_hop": r[3],
            } for r in result]

        return shifts[:MAX_CHANGES]


def _find_bgp_as_path_changes(snapshot_1: str, snapshot_2: str, device: str | None) -> list[dict]:
    """Find BGP routes where AS_PATH changed.

    NOTE (ISSUE-012): v_routes_auto does not expose an as_path column — the LLM
    discovery recipe maps the BGP RIB columns available in show ip bgp output but
    as_path is vendor-inconsistent.  Returns an empty list until a dedicated
    v_bgp_rib_auto view with an as_path column is available.
    """
    # TODO: implement once v_bgp_rib_auto exposes as_path
    return []  # noqa: RET504

    # ── Dead reference preserved for archaeology ──
    # FROM bgp_routes → now v_routes_auto WHERE protocol IN ('B','b','bgp','BGP')
    # as_path column not yet available in v_routes_auto
    changes = []  # unreachable
    for r in []:
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


def main(params: dict) -> dict:
    """Detect routing drift between snapshots."""
    try:
        args = RoutingDriftInput(**params)
    except Exception as e:
        return RoutingDriftOutput(status="error", error=f"Invalid parameters: {str(e)}").model_dump(
            exclude_none=True
        )

    snapshot_1 = args.snapshot_id_1
    snapshot_2 = args.snapshot_id_2
    device = args.device_name

    try:
        # Find lost routes
        lost = _find_lost_routes(snapshot_1, snapshot_2, device)

        # Find next-hop shifts
        shifts = _find_next_hop_shifts(snapshot_1, snapshot_2, device)

        # Find BGP AS_PATH changes
        bgp_changes = _find_bgp_as_path_changes(snapshot_1, snapshot_2, device)

        total = len(lost) + len(shifts) + len(bgp_changes)

        # Generate summary if exceeds limit
        summary = None
        if total > MAX_CHANGES:
            summary = (
                f"And {total - MAX_CHANGES} other changes not shown (limited to {MAX_CHANGES})"
            )

        return RoutingDriftOutput(
            status="success",
            device_name=device,
            lost_destinations=lost[:MAX_CHANGES],
            path_shifts=shifts,
            bgp_as_path_changes=bgp_changes,
            total_changes=total,
            summary=summary,
            message=f"Found {total} routing changes",
        ).model_dump(exclude_none=True)

    except Exception as e:
        return RoutingDriftOutput(status="error", error=str(e)).model_dump(exclude_none=True)


# =============================================================================
# LangChain Tool Registration
# =============================================================================


@tool
def diff_routing_drift(
    snapshot_id_1: str, snapshot_id_2: str, device_name: str | None = None
) -> dict:
    """Detect routing changes between snapshots.

    Identifies:
    - Lost prefixes (reachable in T1, missing in T2)
    - Next-hop path shifts (same prefix, different next_hop)
    - BGP AS_PATH changes (path selection differences)

    Limited to 20 changes to prevent context overflow.

    Args:
        snapshot_id_1: Baseline/Before snapshot ID
        snapshot_id_2: Target/After snapshot ID
        device_name: Optional device to filter by

    Returns:
        Dictionary with lost_destinations, path_shifts, and bgp_as_path_changes

    Examples:
        >>> diff_routing_drift("20260226_100000", "20260226_120000")
        >>> diff_routing_drift("20260226_100000", "20260226_120000", device_name="R1")
    """
    return main(
        {"snapshot_id_1": snapshot_id_1, "snapshot_id_2": snapshot_id_2, "device_name": device_name}
    )


if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        if not input_str:
            input_data = {}
        else:
            input_data = json.loads(input_str)

        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        sys.exit(1)

#!/usr/bin/env python3
"""
Topology Drift Tool - Detect physical link state changes between snapshots.

Compares topology_links table to find:
- Links that went DOWN (existed in T1, not in T2)
- Links that came UP (existed in T2, not in T1)
- Status changes (exist in both, but link_status changed)

Usage:
    diff_topology_drift(snapshot_id_1="20260226_100000", snapshot_id_2="20260226_120000")
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


class TopologyDriftInput(BaseModel):
    """Input for topology drift detection."""

    snapshot_id_1: str = Field(..., description="Baseline/Before snapshot ID")
    snapshot_id_2: str = Field(..., description="Target/After snapshot ID")


class TopologyDriftOutput(BaseModel):
    """Output from topology drift detection."""

    status: str = Field(..., description="success | error")
    links_down: list[dict] = Field(default_factory=list, description="Links that went down")
    links_up: list[dict] = Field(default_factory=list, description="Links that came up")
    status_changes: list[dict] = Field(
        default_factory=list, description="Links with status changes"
    )
    total_changes: int = Field(default=0, description="Total number of changes")
    message: str | None = Field(default=None, description="Additional info")
    error: str | None = Field(default=None, description="Error message if status=error")


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
    with duckdb.connect(str(MAIN_DB_PATH)) as conn:
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


def main(params: dict) -> dict:
    """Detect topology drift between snapshots."""
    try:
        args = TopologyDriftInput(**params)
    except Exception as e:
        return TopologyDriftOutput(
            status="error", error=f"Invalid parameters: {str(e)}"
        ).model_dump(exclude_none=True)

    snapshot_1 = args.snapshot_id_1
    snapshot_2 = args.snapshot_id_2

    try:
        # Get links for both snapshots
        links_t1 = _get_topology_links(snapshot_1)
        links_t2 = _get_topology_links(snapshot_2)

        # Find links that went down (in T1 but not T2)
        links_down = []
        for edge_key, link in links_t1.items():
            if edge_key not in links_t2:
                links_down.append(link)

        # Find links that came up (in T2 but not T1)
        links_up = []
        for edge_key, link in links_t2.items():
            if edge_key not in links_t1:
                links_up.append(link)

        # Find status changes (exist in both, but status changed)
        status_changes = []
        for edge_key, link_t1 in links_t1.items():
            if edge_key in links_t2:
                link_t2 = links_t2[edge_key]
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

        return TopologyDriftOutput(
            status="success",
            links_down=links_down,
            links_up=links_up,
            status_changes=status_changes,
            total_changes=total,
            message=f"Found {total} topology changes",
        ).model_dump(exclude_none=True)

    except Exception as e:
        return TopologyDriftOutput(status="error", error=str(e)).model_dump(exclude_none=True)


# =============================================================================
# LangChain Tool Registration
# =============================================================================


@tool
def diff_topology_drift(snapshot_id_1: str, snapshot_id_2: str) -> dict:
    """Detect physical topology changes between snapshots.

    Identifies:
    - Links that went DOWN (existed in T1, not in T2)
    - Links that came UP (existed in T2, not in T1)
    - Status changes (exist in both, but link_status changed)

    Args:
        snapshot_id_1: Baseline/Before snapshot ID
        snapshot_id_2: Target/After snapshot ID

    Returns:
        Dictionary with links_down, links_up, and status_changes

    Examples:
        >>> diff_topology_drift("20260226_100000", "20260226_120000")
    """
    return main({"snapshot_id_1": snapshot_id_1, "snapshot_id_2": snapshot_id_2})


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

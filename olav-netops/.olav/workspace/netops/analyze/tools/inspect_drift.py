"""inspect_drift_* @tools — typed wrappers for snapshot-diff helpers.

Replaces the sandbox-global ``diff_sql_state`` / ``diff_topology_drift``
/ ``diff_routing_drift`` / ``diff_configs`` access pattern with @tool
calls.  Same small-model rationale as the inspect_* family in
R-AGENT-HIERARCHY post-Phase-D (2026-05-09): typed args + typed
return, no LLM-side Python composition.

Used primarily by the ``analyze`` sub-agent for drift detection
between two snapshots; ``sim`` may also use these for change-impact
context if needed.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

# Eager imports — lazy imports inside @tool bodies caused
# `_ModuleLock` deadlocks when LangGraph ran multiple drift tools in
# parallel via asyncio.gather (two threads racing the same import
# chain). Top-level import happens once, single-threaded, at agent
# registration time.
from olav_netops.core.diff.sql_state import diff_sql_state
from olav_netops.core.diff.topology_drift import diff_topology_drift
from olav_netops.core.diff.routing_drift import diff_routing_drift
from olav_netops.core.diff.configs import diff_configs


@tool
def inspect_drift_sql(
    table_name: str,
    snapshot_1: str,
    snapshot_2: str,
) -> dict[str, Any]:
    """
    Diff any operational table between two snapshots.

    Returns rows that disappeared (``missing_in_t2``) and rows that
    appeared (``new_in_t2``) — the delta between snapshots.  Use
    this for any table-level drift analysis (devices, parsed_outputs,
    raw_output_store, etc.).

    Args:
        table_name: ``netops.<table>`` qualified name OR bare table
            name.  E.g. ``"devices"`` or ``"netops.parsed_outputs"``.
        snapshot_1: Earlier snapshot_id.
        snapshot_2: Later snapshot_id.

    Returns:
        ``{"missing_in_t2": [...], "new_in_t2": [...],
           "table_name": "...", "snapshot_1": "...", "snapshot_2": "..."}``.

    Example:
        >>> inspect_drift_sql("devices", "snap_pre", "snap_post")
        {"missing_in_t2": [{"hostname": "R5", ...}],   # R5 disappeared
         "new_in_t2":     [{"hostname": "R6", ...}],   # R6 appeared
         ...}
    """
    return diff_sql_state(table_name, snapshot_1, snapshot_2, row_limit=50)


@tool
def inspect_drift_topology(
    snapshot_1: str,
    snapshot_2: str,
) -> dict[str, Any]:
    """
    Diff L2 topology (LLDP/CDP links) between two snapshots.

    Returns links that went away, new links discovered, and links
    that changed status (up→down, down→up).  Use for "what links
    changed between yesterday and today?".

    Args:
        snapshot_1: Earlier snapshot_id.
        snapshot_2: Later snapshot_id.

    Returns:
        ``{"removed_links": [...], "added_links": [...],
           "status_changed": [...]}``.
    """
    return diff_topology_drift(snapshot_1, snapshot_2)


@tool
def inspect_drift_routing(
    snapshot_1: str,
    snapshot_2: str,
) -> dict[str, Any]:
    """
    Diff routing-table state (BGP / OSPF / static) between snapshots.

    Returns prefixes that disappeared, new prefixes, and entries
    where next-hop / AS-PATH / metric changed.  Use for "what
    routes flapped overnight?".

    Args:
        snapshot_1: Earlier snapshot_id.
        snapshot_2: Later snapshot_id.

    Returns:
        ``{"prefix_diff": {...}, "next_hop_changes": [...],
           "as_path_changes": [...], ...}``.
    """
    return diff_routing_drift(snapshot_1, snapshot_2)


@tool
def inspect_drift_configs(
    device: str,
    command: str,
    snapshot_1: str | None = None,
    snapshot_2: str | None = None,
) -> dict[str, Any]:
    """
    Diff raw command output for a single device between snapshots.

    Returns added / removed / changed lines.  Use for "what config
    changed on R3 between yesterday and today?".

    Args:
        device: Hostname (must be in ``netops.devices``).
        command: The CLI command whose output to compare,
            e.g. ``"show running-config"``.
        snapshot_1: Earlier snapshot_id.  ``None`` → second-newest.
        snapshot_2: Later snapshot_id.  ``None`` → newest.

    Returns:
        ``{"device": "...", "command": "...",
           "lines_added": [...], "lines_removed": [...]}``.
    """
    return diff_configs(device, command, snapshot_1, snapshot_2)

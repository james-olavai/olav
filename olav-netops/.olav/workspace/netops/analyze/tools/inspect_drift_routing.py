"""inspect_drift_routing — diff routing-table state between snapshots."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from olav_netops.core.diff.routing_drift import diff_routing_drift
from olav_netops.core.diff._tool_helpers import (
    drift_budget_check,
    normalize_error,
    validate_snapshots,
)


@tool
def inspect_drift_routing(
    snapshot_1: str,
    snapshot_2: str,
) -> dict[str, Any]:
    """
    Diff routing-table state (BGP / OSPF / static) between snapshots.

    NOTE: this helper depends on a ``routes`` table that may not exist
    in all deployments (R-VERTICAL-SLICE 2026-05-09 finding: demo7
    DBs don't materialise it).  When unavailable, the error envelope
    returned will say ``Table with name routes does not exist`` —
    fall back to ``inspect_drift_sql("v_show_ip_route_auto", ...)``
    or ``inspect_drift_configs(device, "show ip route", ...)`` for
    the same insight.

    Args:
        snapshot_1: Earlier snapshot_id.
        snapshot_2: Later snapshot_id.

    Returns:
        On success: ``{status: success, prefix_diff, next_hop_changes,
                       as_path_changes, ...}``.
        On error:   ``{status: error, error_kind, message, ...}``.
    """
    budget = drift_budget_check(("routing", snapshot_1, snapshot_2))
    if budget is not None:
        return budget
    err = validate_snapshots([snapshot_1, snapshot_2])
    if err:
        return err
    result = diff_routing_drift(snapshot_1, snapshot_2)
    if result.get("status") == "error":
        return normalize_error(
            result,
            tool_name="inspect_drift_routing",
            args={"snapshot_1": snapshot_1, "snapshot_2": snapshot_2},
        )
    return result

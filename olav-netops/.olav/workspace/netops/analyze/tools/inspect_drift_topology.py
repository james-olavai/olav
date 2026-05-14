"""inspect_drift_topology — diff L2 topology (LLDP/CDP) between snapshots."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from olav_netops.core.diff.topology_drift import diff_topology_drift
from olav_netops.core.diff._tool_helpers import (
    drift_budget_check,
    normalize_error,
    validate_snapshots,
)


@tool
def inspect_drift_topology(
    snapshot_1: str,
    snapshot_2: str,
) -> dict[str, Any]:
    """
    Diff L2 topology (LLDP/CDP links) between two snapshots.

    Returns links that went away, new links discovered, and links
    that changed status (up→down, down→up).

    Args:
        snapshot_1: Earlier snapshot_id.
        snapshot_2: Later snapshot_id.

    Returns:
        On success: ``{status: success, links_down: [...],
                       links_up: [...], status_changes: [...],
                       total_changes}``.
        On error:   ``{status: error, error_kind, message, ...}``.
    """
    budget = drift_budget_check(("topology", snapshot_1, snapshot_2))
    if budget is not None:
        return budget
    err = validate_snapshots(
        [snapshot_1, snapshot_2],
        table="netops.topology_links",
    )
    if err:
        return err
    result = diff_topology_drift(snapshot_1, snapshot_2)
    if result.get("status") == "error":
        return normalize_error(
            result,
            tool_name="inspect_drift_topology",
            args={"snapshot_1": snapshot_1, "snapshot_2": snapshot_2},
        )
    return result

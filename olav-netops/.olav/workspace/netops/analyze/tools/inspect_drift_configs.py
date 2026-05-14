"""inspect_drift_configs — diff raw CLI command output for one device."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from olav_netops.core.diff.configs import diff_configs
from olav_netops.core.diff._tool_helpers import (
    drift_budget_check,
    normalize_error,
    validate_snapshots,
)


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
        On success: ``{status: success, device, command, lines_added,
                       lines_removed, ...}``.
        On error:   ``{status: error, error_kind, message, ...}``.
    """
    budget = drift_budget_check(
        ("configs", device, command, snapshot_1, snapshot_2)
    )
    if budget is not None:
        return budget
    snaps_to_validate = [s for s in (snapshot_1, snapshot_2) if s is not None]
    if snaps_to_validate:
        err = validate_snapshots(snaps_to_validate)
        if err:
            return err
    result = diff_configs(device, command, snapshot_1, snapshot_2)
    if result.get("status") == "error":
        return normalize_error(
            result,
            tool_name="inspect_drift_configs",
            args={
                "device": device,
                "command": command,
                "snapshot_1": snapshot_1,
                "snapshot_2": snapshot_2,
            },
        )
    return result

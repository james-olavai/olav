"""inspect_drift_sql — diff any operational table between two snapshots."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from olav_netops.core.diff.sql_state import diff_sql_state
from olav_netops.core.diff._tool_helpers import (
    drift_budget_check,
    normalize_error,
    validate_snapshots,
)


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

    Validates both snapshots exist before running; returns a clean
    ``snapshot_not_found`` error envelope (with available IDs) if not.

    Args:
        table_name: ``netops.<table>`` qualified name OR bare table
            name.  E.g. ``"devices"`` or ``"netops.parsed_outputs"``.
        snapshot_1: Earlier snapshot_id.
        snapshot_2: Later snapshot_id.

    Returns:
        On success: ``{status: success, table, missing_in_t2: [...],
                       new_in_t2: [...], total_missing, total_new}``.
        On error:   ``{status: error, error_kind, message, ...}``.
    """
    budget = drift_budget_check(("sql", table_name, snapshot_1, snapshot_2))
    if budget is not None:
        return budget
    err = validate_snapshots([snapshot_1, snapshot_2])
    if err:
        return err
    result = diff_sql_state(table_name, snapshot_1, snapshot_2, row_limit=50)
    if result.get("status") == "error":
        return normalize_error(
            result,
            tool_name="inspect_drift_sql",
            args={
                "table_name": table_name,
                "snapshot_1": snapshot_1,
                "snapshot_2": snapshot_2,
            },
        )
    return result

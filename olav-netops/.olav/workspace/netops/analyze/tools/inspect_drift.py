"""inspect_drift_* @tools — typed wrappers for snapshot-diff helpers.

Replaces the sandbox-global ``diff_sql_state`` / ``diff_topology_drift``
/ ``diff_routing_drift`` / ``diff_configs`` access pattern with @tool
calls.  Same small-model rationale as the inspect_* family in
R-AGENT-HIERARCHY post-Phase-D (2026-05-09): typed args + typed
return, no LLM-side Python composition.

R-VERTICAL-SLICE follow-on (dev_docs/74): wrappers add uniform
input validation + normalized error envelope so the LLM gets a
consistent ``{status: error, error_kind, message, ...}`` shape
regardless of which underlying helper failed and how.
"""
from __future__ import annotations

from typing import Any

import duckdb
from langchain_core.tools import tool

# Eager imports — lazy imports inside @tool bodies caused
# `_ModuleLock` deadlocks when LangGraph ran multiple drift tools in
# parallel via asyncio.gather (two threads racing the same import
# chain). Top-level import happens once, single-threaded, at agent
# registration time.
from olav.core.config import MAIN_DB_PATH
from olav_netops.core.diff.sql_state import diff_sql_state
from olav_netops.core.diff.topology_drift import diff_topology_drift
from olav_netops.core.diff.routing_drift import diff_routing_drift
from olav_netops.core.diff.configs import diff_configs


# In-process dedup budget — boundary test 1 saw 43 inspect_drift_sql
# calls with the same snapshot pair iterating through tables.  When
# snapshot pair returns empty for one table it usually returns empty
# for adjacent tables too.  Cap at 2 identical calls.
import threading as _threading
_drift_lock = _threading.Lock()
_drift_call_counts: dict[tuple, int] = {}
_DRIFT_DUP_LIMIT = 2


def _drift_budget_check(args_key: tuple) -> dict | None:
    with _drift_lock:
        n = _drift_call_counts.get(args_key, 0)
        _drift_call_counts[args_key] = n + 1
    if n + 1 > _DRIFT_DUP_LIMIT:
        return {
            "status": "error",
            "error_kind": "duplicate_call_budget",
            "message": (
                f"This drift query has been called {n+1} times "
                f"with identical args in this session.  The result "
                f"won't change.  Stop iterating tables — if all you've "
                f"tried so far returned empty, the snapshot pair "
                f"is likely partial / broken.  Validate snapshots "
                f"first, OR accept that nothing has drifted."
            ),
            "args_key": list(args_key),
        }
    return None


def _list_snapshots(table: str = "netops.parsed_outputs") -> list[str]:
    """Return snapshot_ids known to a given table, newest-first lexical."""
    try:
        with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
            rows = conn.execute(
                f"SELECT DISTINCT snapshot_id FROM {table} "
                "ORDER BY snapshot_id DESC"
            ).fetchall()
            return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def _validate_snapshots(
    snapshots: list[str],
    *,
    table: str = "netops.parsed_outputs",
) -> dict[str, Any] | None:
    """Return error envelope if any snapshot is unknown; else None."""
    available = _list_snapshots(table)
    available_set = set(available)
    missing = [s for s in snapshots if s not in available_set]
    if not missing:
        return None
    return {
        "status": "error",
        "error_kind": "snapshot_not_found",
        "missing_snapshots": missing,
        "available_snapshots": available[:10],
        "message": (
            f"Snapshot(s) {missing} not found in {table}. "
            f"Recent available: {available[:5]}.  "
            f"Re-call with one of the available snapshot IDs."
        ),
    }


def _normalize_error(
    raw: dict[str, Any],
    *,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Convert helper's ad-hoc error shape into a uniform envelope."""
    msg = raw.get("error") or raw.get("message") or "(no error message)"
    return {
        "status": "error",
        "error_kind": "diff_helper_failed",
        "message": str(msg),
        "tool": tool_name,
        "args": args,
    }


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
    budget = _drift_budget_check(("sql", table_name, snapshot_1, snapshot_2))
    if budget is not None:
        return budget
    err = _validate_snapshots([snapshot_1, snapshot_2])
    if err:
        return err
    result = diff_sql_state(table_name, snapshot_1, snapshot_2, row_limit=50)
    if result.get("status") == "error":
        return _normalize_error(result, tool_name="inspect_drift_sql",
                                args={"table_name": table_name,
                                      "snapshot_1": snapshot_1,
                                      "snapshot_2": snapshot_2})
    return result


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
    budget = _drift_budget_check(("topology", snapshot_1, snapshot_2))
    if budget is not None:
        return budget
    err = _validate_snapshots([snapshot_1, snapshot_2],
                              table="netops.topology_links")
    if err:
        return err
    result = diff_topology_drift(snapshot_1, snapshot_2)
    if result.get("status") == "error":
        return _normalize_error(result, tool_name="inspect_drift_topology",
                                args={"snapshot_1": snapshot_1,
                                      "snapshot_2": snapshot_2})
    return result


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
    budget = _drift_budget_check(("routing", snapshot_1, snapshot_2))
    if budget is not None:
        return budget
    err = _validate_snapshots([snapshot_1, snapshot_2])
    if err:
        return err
    result = diff_routing_drift(snapshot_1, snapshot_2)
    if result.get("status") == "error":
        return _normalize_error(result, tool_name="inspect_drift_routing",
                                args={"snapshot_1": snapshot_1,
                                      "snapshot_2": snapshot_2})
    return result


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
    budget = _drift_budget_check(("configs", device, command, snapshot_1, snapshot_2))
    if budget is not None:
        return budget
    snaps_to_validate = [s for s in (snapshot_1, snapshot_2) if s is not None]
    if snaps_to_validate:
        err = _validate_snapshots(snaps_to_validate)
        if err:
            return err
    result = diff_configs(device, command, snapshot_1, snapshot_2)
    if result.get("status") == "error":
        return _normalize_error(result, tool_name="inspect_drift_configs",
                                args={"device": device, "command": command,
                                      "snapshot_1": snapshot_1,
                                      "snapshot_2": snapshot_2})
    return result

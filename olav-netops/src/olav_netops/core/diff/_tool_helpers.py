"""Shared helpers for the inspect_drift_* @tool family.

Extracted from the old monolithic ``inspect_drift.py`` when it was
split into one file per tool (one-tool-per-file convention, parity
with all other ``inspect_*`` tools).  Lives in the olav_netops Python
package so each split tool file can import via a stable path —
workspace-tool files are loaded as isolated specs and can't import
each other directly.

Provides:

* ``drift_budget_check`` — in-process dedup budget (cap N identical
  calls per session) so a confused LLM iterating tables doesn't
  burn 40+ tool calls on a snapshot pair that returns empty.
* ``validate_snapshots`` — pre-flight check that the requested
  snapshot IDs exist in the target table, with a clean error
  envelope (including the most recent available IDs) when missing.
* ``normalize_error`` — convert the helpers' ad-hoc error shapes
  into a uniform ``{status: error, error_kind, message, ...}``
  envelope the LLM can parse consistently.
"""
from __future__ import annotations

import threading
from typing import Any

import duckdb

from olav.core.config import MAIN_DB_PATH

_drift_lock = threading.Lock()
_drift_call_counts: dict[tuple, int] = {}
DRIFT_DUP_LIMIT = 2


def drift_budget_check(args_key: tuple) -> dict | None:
    """Return an error envelope if this call has already run twice
    with the same args; else ``None`` to let the caller proceed."""
    with _drift_lock:
        n = _drift_call_counts.get(args_key, 0)
        _drift_call_counts[args_key] = n + 1
    if n + 1 > DRIFT_DUP_LIMIT:
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


def validate_snapshots(
    snapshots: list[str],
    *,
    table: str = "netops.parsed_outputs",
) -> dict[str, Any] | None:
    """Return error envelope if any snapshot is unknown; else ``None``."""
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


def normalize_error(
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


__all__ = [
    "DRIFT_DUP_LIMIT",
    "drift_budget_check",
    "validate_snapshots",
    "normalize_error",
]

"""olav log — audit query commands backed by audit.duckdb.

Public API (also used by CLI sub-commands):
    log_list(db_path, hours)            — runs in last N hours (default 24)
    log_show(run_id, db_path)           — full event sequence for one run
    log_errors(db_path, since_hours)    — error/failed events within window
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_ERROR_TYPES = frozenset(
    [
        "tool_call_error",
        "run_error",
        "run_cancelled",
        "tool_call_failed",
        "llm_error",
    ]
)


def _connect(db_path: Path | str | None):
    import duckdb

    from olav.core.config import AUDIT_DB_PATH

    path = str(db_path) if db_path is not None else str(AUDIT_DB_PATH)
    if not Path(path).exists():
        return None
    return duckdb.connect(path, read_only=True)


def log_list(
    db_path: Path | str | None = None,
    *,
    hours: int = 24,
) -> list[dict[str, Any]]:
    """Return audit runs started within the last *hours* hours.

    Each item is a dict with keys: run_id, start_time, status, agent_id, user_id.
    Returns an empty list if the audit database has not been initialised yet.
    """
    conn = _connect(db_path)
    if conn is None:
        return []
    try:
        # Table only exists after the first agent run — return empty on fresh install.
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "audit_runs" not in tables:
            return []
        rows = conn.execute(
            """
            SELECT run_id, start_time, status, agent_id, user_id
            FROM audit_runs
            WHERE start_time >= now() - INTERVAL (?) HOUR
            ORDER BY start_time DESC
            """,
            [hours],
        ).fetchall()
        cols = ["run_id", "start_time", "status", "agent_id", "user_id"]
        return [dict(zip(cols, row, strict=True)) for row in rows]
    finally:
        conn.close()


def log_show(
    run_id: str,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return all audit events for *run_id* ordered by sequence_no / timestamp.

    *run_id* may be a full UUID or the 8-character prefix shown by ``log list``.
    Returns an empty list if the audit database has not been initialised yet.
    """
    conn = _connect(db_path)
    if conn is None:
        return []
    try:
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "audit_events" not in tables:
            return []
        # Support 8-char prefix (as shown by log list) as well as full UUID
        if len(run_id) <= 8:
            where, param = "WHERE run_id LIKE ?", [run_id + "%"]
        else:
            where, param = "WHERE run_id = ?", [run_id]
        rows = conn.execute(
            f"""
            SELECT event_id, event_type, timestamp, sequence_no, agent_id, payload
            FROM audit_events
            {where}
            ORDER BY COALESCE(sequence_no, 0), timestamp
            """,
            param,
        ).fetchall()
        cols = ["event_id", "event_type", "timestamp", "sequence_no", "agent_id", "payload"]
        return [dict(zip(cols, row, strict=True)) for row in rows]
    finally:
        conn.close()


def log_errors(
    db_path: Path | str | None = None,
    *,
    since_hours: int | None = None,
) -> list[dict[str, Any]]:
    """Return error/failed audit events, optionally restricted to a recent window.

    Args:
        db_path: Override the default AUDIT_DB_PATH.
        since_hours: If set, only return events from the last N hours.

    Returns an empty list if the audit database has not been initialised yet.
    """
    conn = _connect(db_path)
    if conn is None:
        return []
    try:
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "audit_events" not in tables:
            return []
        type_placeholders = ", ".join("?" * len(_ERROR_TYPES))
        if since_hours is not None:
            error_types = list(_ERROR_TYPES)
            time_ph = "AND timestamp >= now() - INTERVAL (?) HOUR"
            sql = f"""
                SELECT event_id, event_type, timestamp, run_id, agent_id, payload
                FROM audit_events
                WHERE event_type IN ({type_placeholders})
                {time_ph}
                ORDER BY timestamp DESC
            """
            params = error_types + [since_hours]
        else:
            sql = f"""
                SELECT event_id, event_type, timestamp, run_id, agent_id, payload
                FROM audit_events
                WHERE event_type IN ({type_placeholders})
                ORDER BY timestamp DESC
            """
            params = list(_ERROR_TYPES)
        rows = conn.execute(sql, params).fetchall()
        cols = ["event_id", "event_type", "timestamp", "run_id", "agent_id", "payload"]
        return [dict(zip(cols, row, strict=True)) for row in rows]
    finally:
        conn.close()

#!/usr/bin/env python3
# LEGACY-KEEP: the historical reference in the docstring (llm_cache.sqlite /
# olav.json) documents the v0.11.0 → v0.19 migration story for future
# archaeologists. The legacy *code paths* were deleted at the v0.19 cut;
# this marker tells the ARCH-22 D governance pin that the remaining
# "legacy" mention is purely narrative.
"""analyze_logs.py - Structured audit log analysis via audit.duckdb.

Data Source:
- .olav/databases/audit.duckdb  (single source of truth since v0.11.0 audit
  refactor; the legacy llm_cache.sqlite / olav.json paths were removed at
  the v0.19 cut — round-9 grep audit confirmed zero runtime readers).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

from olav.core.config import DATABASES_DIR as _DB_DIR

_DEFAULT_AUDIT_DB = _DB_DIR / "audit.duckdb"


def _analyze_audit_db(
    query: str = "stats",
    hours: int = 24,
    limit: int = 20,
    keyword: str = "",
    db_path: Path | None = None,
) -> dict:
    """Core implementation — accepts optional db_path for testability."""
    db_path = db_path or _DEFAULT_AUDIT_DB
    if not db_path.exists():
        return {"status": "error", "message": f"audit.duckdb not found at {db_path}"}

    query = query.lower().strip()
    keyword = keyword.strip()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn = duckdb.connect(str(db_path), read_only=True)
    except Exception as exc:
        return {"status": "error", "message": f"Cannot open audit.duckdb: {exc}"}

    try:
        if query == "stats":
            rows = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_runs,
                    SUM(CASE WHEN status = 'completed'  THEN 1 ELSE 0 END) AS completed_runs,
                    SUM(CASE WHEN status IN ('error', 'run_error') THEN 1 ELSE 0 END) AS error_runs,
                    SUM(CASE WHEN status = 'cancelled'  THEN 1 ELSE 0 END) AS cancelled_runs
                FROM audit_runs
                WHERE start_time >= ?
                """,
                [cutoff_str],
            ).fetchone()
            return {
                "status": "success",
                "total_runs": rows[0],
                "completed_runs": rows[1],
                "error_runs": rows[2],
                "cancelled_runs": rows[3],
                "window_hours": hours,
            }

        elif query == "recent":
            rows = conn.execute(
                """
                SELECT run_id, agent_id, status, start_time, end_time, user_id
                FROM audit_runs
                WHERE start_time >= ?
                ORDER BY start_time DESC
                LIMIT ?
                """,
                [cutoff_str, limit],
            ).fetchall()
            return {
                "status": "success",
                "runs": [
                    {
                        "run_id": r[0],
                        "agent_id": r[1],
                        "status": r[2],
                        "start_time": str(r[3]),
                        "end_time": str(r[4]) if r[4] else None,
                        "user_id": r[5],
                    }
                    for r in rows
                ],
            }

        elif query == "errors":
            rows = conn.execute(
                """
                SELECT e.event_type, e.timestamp, e.agent_id, e.payload
                FROM audit_events e
                WHERE e.event_type IN ('tool_call_failed', 'run_error', 'run_cancelled')
                  AND e.timestamp >= ?
                ORDER BY e.timestamp DESC
                LIMIT ?
                """,
                [cutoff_str, limit],
            ).fetchall()
            events = []
            for r in rows:
                payload = {}
                try:
                    payload = json.loads(r[3]) if r[3] else {}
                except (json.JSONDecodeError, TypeError):
                    pass
                events.append({
                    "event_type": r[0],
                    "timestamp": str(r[1]),
                    "agent_id": r[2],
                    **payload,
                })
            return {"status": "success", "events": events}

        elif query == "tool_usage":
            rows = conn.execute(
                """
                SELECT
                    json_extract_string(payload, '$.tool') AS tool,
                    COUNT(*) AS count
                FROM audit_events
                WHERE event_type = 'tool_call_started'
                  AND timestamp >= ?
                GROUP BY tool
                ORDER BY count DESC
                LIMIT ?
                """,
                [cutoff_str, limit],
            ).fetchall()
            return {
                "status": "success",
                "tools": [{"tool": r[0], "count": r[1]} for r in rows if r[0]],
            }

        elif query == "models":
            rows = conn.execute(
                """
                SELECT
                    json_extract_string(payload, '$.model') AS model,
                    SUM(CAST(json_extract_string(payload, '$.tokens_in')  AS INTEGER)) AS tokens_in,
                    SUM(CAST(json_extract_string(payload, '$.tokens_out') AS INTEGER)) AS tokens_out,
                    COUNT(*) AS calls
                FROM audit_events
                WHERE event_type = 'llm_usage'
                  AND timestamp >= ?
                GROUP BY model
                ORDER BY tokens_in DESC NULLS LAST
                LIMIT ?
                """,
                [cutoff_str, limit],
            ).fetchall()
            return {
                "status": "success",
                "models": [
                    {
                        "model": r[0],
                        "tokens_in": int(r[1]) if r[1] is not None else 0,
                        "tokens_out": int(r[2]) if r[2] is not None else 0,
                        "calls": r[3],
                    }
                    for r in rows
                ],
            }

        else:
            return {
                "status": "error",
                "message": f"unknown query type '{query}'. Use: stats, recent, errors, tool_usage, models",
            }

    except Exception as exc:
        return {"status": "error", "message": str(exc)}
    finally:
        conn.close()


def analyze_logs(
    query: str = "stats",
    hours: int = 24,
    limit: int = 20,
    keyword: str = "",
) -> dict:
    """Analyze OLAV execution audit logs from audit.duckdb.

    Args:
        query: One of: stats, recent, errors, tool_usage, models
            - stats:      Success/error/cancelled counts for the time window
            - recent:     Most recent runs with status
            - errors:     Recent tool_call_failed / run_error events
            - tool_usage: Most called tools ranked by invocation count
            - models:     Token usage aggregated by model
        hours: Time window in hours (default 24)
        limit: Maximum rows to return (default 20)
        keyword: Unused (reserved for future full-text search)

    Returns:
        dict with "status" ("success" or "error") and query-specific fields.
    """
    return _analyze_audit_db(query=query, hours=hours, limit=limit, keyword=keyword)


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = analyze_logs(**_args)
    print(_json.dumps(result, default=str))

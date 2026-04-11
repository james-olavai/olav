"""Search Logs Tool — Query syslog Parquet data for agents.

Agents use this to answer questions like:
  - "What errors occurred in the last hour?"
  - "Which devices sent the most syslog messages today?"
  - "Were there any critical events on R1 yesterday?"

Data source: .olav/databases/logs/**/*.parquet
Written by: src/olav/services/syslog_receiver.py
"""

import logging
import sys
from pathlib import Path


def _find_project_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

from langchain_core.tools import tool

_logger = logging.getLogger(__name__)

_SEVERITY_LEVELS = {
    "emergency", "alert", "critical", "error",
    "warning", "notice", "info", "debug",
}


def _get_log_dir() -> Path:
    """Resolve the syslog Parquet log directory."""
    try:
        from olav.core.config import DATABASES_DIR
        return Path(DATABASES_DIR) / "logs"
    except Exception:
        return Path(".olav/databases/logs")


@tool
def search_logs(
    query: str,
    hours: int = 24,
    severity: str | None = None,
    host: str | None = None,
    limit: int = 50,
) -> str:
    """Search syslog records stored as Parquet files.

    Args:
        query: Keyword to search in the message field (case-insensitive). Use "" for no filter.
        hours: How many hours back to look (default 24).
        severity: Filter by syslog severity level: emergency/alert/critical/error/warning/notice/info/debug.
        host: Filter by device hostname (partial match).
        limit: Maximum number of results to return (default 50).

    Returns:
        Formatted table of matching syslog entries, newest first.
        Returns "No log records found." when the result set is empty.
    """
    import duckdb

    log_dir = _get_log_dir()
    if not log_dir.exists():
        return "No log records found. (log directory does not exist)"

    # Glob all parquet files recursively
    parquet_files = list(log_dir.rglob("*.parquet"))
    if not parquet_files:
        return "No log records found. (no Parquet files in log directory)"

    parquet_glob = str(log_dir / "**/*.parquet")

    where_parts = [f"TRY_CAST(timestamp AS TIMESTAMP) >= CAST(now() AS TIMESTAMP) - INTERVAL '{hours} hours'"]

    if severity:
        sev = severity.lower()
        if sev in _SEVERITY_LEVELS:
            where_parts.append(f"severity = '{sev}'")
        else:
            return (
                f"Invalid severity '{severity}'. "
                f"Valid values: {', '.join(sorted(_SEVERITY_LEVELS))}"
            )

    if host:
        # Escape single quotes in host filter
        safe_host = host.replace("'", "''")
        where_parts.append(f"host ILIKE '%{safe_host}%'")

    if query:
        safe_query = query.replace("'", "''")
        where_parts.append(f"message ILIKE '%{safe_query}%'")

    where_clause = " AND ".join(where_parts)

    sql = f"""
        SELECT timestamp, host, severity, facility, message
        FROM read_parquet('{parquet_glob}', union_by_name=true)
        WHERE {where_clause}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """

    try:
        con = duckdb.connect(":memory:")
        rows = con.execute(sql).fetchall()
        con.close()
    except Exception as exc:
        _logger.warning("search_logs query error: %s", exc)
        return f"Error querying logs: {exc}"

    if not rows:
        return "No log records found matching the criteria."

    lines = [f"{'TIMESTAMP':<24} {'HOST':<16} {'SEV':<10} {'FACILITY':<10} MESSAGE"]
    lines.append("-" * 100)
    for ts, h, sev, fac, msg in rows:
        ts_str = str(ts)[:23] if ts else "-"
        h_str = (str(h) or "-")[:14]
        sev_str = (str(sev) or "-")[:8]
        fac_str = (str(fac) or "-")[:8]
        msg_str = (str(msg) or "")[:80]
        lines.append(f"{ts_str:<24} {h_str:<16} {sev_str:<10} {fac_str:<10} {msg_str}")

    header = f"Found {len(rows)} syslog records (last {hours}h"
    if severity:
        header += f", severity={severity}"
    if host:
        header += f", host={host}"
    if query:
        header += f", query='{query}'"
    header += "):\n"

    return header + "\n".join(lines)

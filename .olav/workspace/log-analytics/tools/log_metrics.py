#!/usr/bin/env python3
"""
Log Metrics Query Tool - DuckDB in-memory Parquet query.

Core Features:
1. Query Parquet log files via DuckDB in-memory mode
2. Dynamic log storage path discovery
3. Time-range filtering and aggregation
4. Severity-based filtering

Usage in DeepAgents:
    from .tools import log_metrics_query
    agent = create_deep_agent(tools=[log_metrics_query.log_metrics_query])
"""

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field, validator


# Add src to Python Path
def _find_project_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

import duckdb as _duckdb

from olav.core.config import LOG_STORAGE_DIR, MAIN_DB_PATH, DATABASES_DIR


def _get_log_storage_path() -> Path:
    """Get the log storage directory path."""
    log_path = Path(LOG_STORAGE_DIR)
    log_path.mkdir(parents=True, exist_ok=True)
    return log_path


def _discover_parquet_files(
    log_path: Path, start_date: str | None = None, end_date: str | None = None
) -> list[str]:
    """Discover Parquet files in the log storage directory."""
    parquet_files = []

    if not log_path.exists():
        return parquet_files

    # Scan for Parquet files
    for f in log_path.rglob("*.parquet"):
        # Filter by date if specified
        if start_date or end_date:
            # Extract date from filename or parent directory
            date_str = f.stem[:10] if len(f.stem) >= 10 else f.parent.name
            if start_date and date_str < start_date:
                continue
            if end_date and date_str > end_date:
                continue
        parquet_files.append(str(f))

    return sorted(parquet_files)


def log_query(
    sql: str,
    start_date: str | None = None,
    end_date: str | None = None,
    parquet_pattern: str | None = None,
) -> list[dict]:
    """Execute a SQL query against Parquet log files using DuckDB in-memory mode."""
    log_path = _get_log_storage_path()

    # Discover Parquet files
    if parquet_pattern:
        # Use specific pattern
        full_pattern = str(log_path / parquet_pattern)
    else:
        # Use all Parquet files in the log directory
        parquet_files = _discover_parquet_files(log_path, start_date, end_date)
        if not parquet_files:
            # Fallback: try generic pattern
            full_pattern = str(log_path / "**/*.parquet")
        else:
            # Use discovered files
            full_pattern = ",".join(parquet_files) if len(parquet_files) > 1 else parquet_files[0]

    # Connect to DuckDB in-memory and query
    conn = _duckdb.connect(":memory:")

    try:
        # Register Parquet files
        if "*" in full_pattern or "," in full_pattern:
            # Multiple files or pattern
            query = f"SELECT * FROM read_parquet('{full_pattern}')"
        else:
            # Single file
            query = f"SELECT * FROM read_parquet('{full_pattern}')"

        # Execute the user's query
        conn.execute(query)
        result = conn.execute(sql).fetchall()

        # Get column names
        if conn.description:
            cols = [d[0] for d in conn.description]
            return [dict(zip(cols, row, strict=False)) for row in result]
        return []

    finally:
        conn.close()


class LogMetricsInput(BaseModel):
    """Log metrics query input parameters."""

    query: str = Field(default="", description="Natural language query about log metrics")
    sql: str = Field(default="", description="Direct SQL query (optional)")
    start_date: str | None = Field(default=None, description="Start date (YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="End date (YYYY-MM-DD)")
    severity: str | None = Field(
        default=None, description="Filter by severity (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    host: str | None = Field(default=None, description="Filter by host/device")
    limit: int = Field(default=100, description="Maximum number of results")

    @validator("query", "sql", pre=True)
    def validate_not_none(cls, v):
        if v is None:
            return ""
        return v


class LogMetricsOutput(BaseModel):
    """Log metrics query output format."""

    data: list[dict] | None = Field(default=None, description="Query results")
    sql: str | None = Field(default=None, description="SQL query executed")
    count: int | None = Field(default=None, description="Number of results")
    status: str = Field(..., description="success | error | no_data | needs_sql_generation")
    error: str | None = Field(default=None, description="Error message if status=error")
    log_storage_path: str | None = Field(default=None, description="Log storage path used")
    parquet_files_found: int | None = Field(
        default=None, description="Number of Parquet files discovered"
    )


def _sanitize_value(val: Any) -> Any:
    """Convert non-JSON-serializable types to strings."""
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, dict):
        return {k: _sanitize_value(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_sanitize_value(v) for v in val]
    return val


def _sanitize_rows(rows: list[dict]) -> list[dict]:
    """Ensure all values in query results are JSON-serializable."""
    return [_sanitize_value(row) for row in rows]


def main(params: dict) -> dict:
    """Execute log metrics query.

    Args:
        params: {
            "query": "Natural language query",
            "sql": "Optional direct SQL",
            "start_date": "YYYY-MM-DD",
            "end_date": "YYYY-MM-DD",
            "severity": "ERROR",
            "host": "device-01",
            "limit": 100
        }

    Returns:
        Query results with status
    """
    try:
        args = LogMetricsInput(**params)
    except Exception as e:
        return LogMetricsOutput(status="error", error=f"Invalid parameters: {str(e)}").model_dump(
            exclude_none=True
        )

    log_path = _get_log_storage_path()
    parquet_files = _discover_parquet_files(log_path, args.start_date, args.end_date)

    # If no Parquet files, return empty with helpful message
    if not parquet_files:
        return LogMetricsOutput(
            status="no_data",
            log_storage_path=str(log_path),
            parquet_files_found=0,
            message=f"No Parquet files found in {log_path}. Log files should be stored as .olav/databases/logs/YYYY-MM-DD/*.parquet",
        ).model_dump(exclude_none=True)

    # Build SQL query
    direct_sql = args.sql
    user_query = args.query
    direct_sql = args.sql

    if direct_sql:
        # Execute direct SQL
        try:
            results = log_query(sql=direct_sql, start_date=args.start_date, end_date=args.end_date)
            results = _sanitize_rows(results)

            # Apply limit
            limited_results = results[: args.limit] if results else []
            truncated = len(results) > args.limit if results else False

            return LogMetricsOutput(
                data=limited_results,
                sql=direct_sql,
                count=len(results),
                status="success",
                log_storage_path=str(log_path),
                parquet_files_found=len(parquet_files),
                message=f"Found {len(results)} results. Showing {len(limited_results)}."
                if truncated
                else None,
            ).model_dump(exclude_none=True)

        except Exception as e:
            return LogMetricsOutput(
                status="error",
                error=str(e),
                log_storage_path=str(log_path),
                parquet_files_found=len(parquet_files),
            ).model_dump(exclude_none=True)

    # Return schema context for SQL generation
    sample_sql = f"""-- Example: Count errors by severity in the last 24 hours
SELECT severity, count(*) as count
FROM read_parquet('{log_path}/**/*.parquet')
WHERE timestamp >= now() - interval '24 hours'
GROUP BY severity
ORDER BY count DESC
LIMIT 10

-- Example: Get recent ERROR logs from a specific host
SELECT timestamp, host, message
FROM read_parquet('{log_path}/**/*.parquet')
WHERE severity = 'ERROR' 
  AND host = '{args.host or "your-host"}'
  AND timestamp >= now() - interval '1 hour'
ORDER BY timestamp DESC
LIMIT {args.limit}"""

    return LogMetricsOutput(
        status="needs_sql_generation",
        log_storage_path=str(log_path),
        parquet_files_found=len(parquet_files),
        message=f"Found {len(parquet_files)} Parquet files. Provide SQL query to execute.",
        schema_context=sample_sql,
    ).model_dump(exclude_none=True)


# ============================================================================
# LangChain Tool Registration
# ============================================================================


@tool
def log_metrics_query(
    query: str = "",
    sql: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    severity: str | None = None,
    host: str | None = None,
    limit: int = 100,
) -> dict:
    """Query log metrics from Parquet files via DuckDB in-memory mode.

    WHEN TO USE:
    - Log count aggregation by severity, host, time window
    - Time-series trends (errors per minute/hour)
    - Finding specific error patterns in historical logs
    - Full audit log queries

    DATA STORAGE:
    - Parquet files in .olav/databases/logs/YYYY-MM-DD/
    - Use DuckDB read_parquet() to query

    FEATURES:
    - Dynamic Parquet file discovery
    - Time-range filtering
    - Severity-based filtering
    - Host/device filtering

    Args:
        query: Natural language question about log metrics
        sql: Optional direct SQL query
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        severity: Filter by severity (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        host: Filter by host/device name
        limit: Maximum results (default 100)

    Returns:
        Query results with status, count, and SQL executed

    Examples:
        Example 1 - Count errors by severity:
        >>> log_metrics_query(sql="SELECT severity, count(*) as cnt FROM read_parquet('.olav/databases/logs/**/*.parquet') GROUP BY severity")

        Example 2 - Get recent errors:
        >>> log_metrics_query(severity="ERROR", limit=50)

        Example 3 - Time range query:
        >>> log_metrics_query(start_date="2026-02-01", end_date="2026-02-28", severity="ERROR")
    """
    params = {
        "query": query,
        "sql": sql,
        "start_date": start_date,
        "end_date": end_date,
        "severity": severity,
        "host": host,
        "limit": limit,
    }
    return main(params)


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return super().default(obj)


if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        if not input_str:
            input_data = {}
        else:
            input_data = json.loads(input_str)

        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2, cls=DateTimeEncoder))
    except Exception as e:
        print(
            json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False), file=sys.stderr
        )
        sys.exit(1)

"""olav.tools.sql — DuckDB query execution (platform-agnostic).

Core SQL query logic used by the `execute_sql` workspace tool.
Can be used standalone without OLAV workspace::

    from olav.tools.sql import query_duckdb, classify_sql

    results = query_duckdb("SELECT * FROM netops.devices")
    sql_type = classify_sql("SELECT * FROM netops.devices")  # → "SELECT"
"""

from __future__ import annotations

from olav.core.db_write import open_write_connection

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def classify_sql(sql: str) -> str:
    """Classify a SQL statement as SELECT, INSERT, MUTATE, DDL, or OTHER."""
    normalized = sql.strip().upper().lstrip("(")
    if normalized.startswith(("SELECT", "WITH", "DESCRIBE", "SHOW", "EXPLAIN")):
        return "SELECT"
    if normalized.startswith(("INSERT", "UPSERT", "COPY")):
        return "INSERT"
    if normalized.startswith(("UPDATE", "DELETE", "TRUNCATE")):
        return "MUTATE"
    if normalized.startswith(("CREATE", "DROP", "ALTER")):
        return "DDL"
    return "OTHER"


def query_duckdb(
    sql: str,
    db_path: str | Path | None = None,
    params: list | None = None,
    read_only: bool = True,
) -> list[dict[str, Any]]:
    """Execute a SQL query against a DuckDB database.

    Args:
        sql: SQL query string.
        db_path: Path to DuckDB file. If None, uses MAIN_DB_PATH from config.
        params: Optional query parameters.
        read_only: If True, opens connection in read-only mode (default).

    Returns:
        List of dicts (column_name → value) for each row.
        For mutating SQL, returns a single-element list with approval requirement.

    Example::

        from olav.tools.sql import query_duckdb

        devices = query_duckdb("SELECT * FROM netops.devices")
        for d in devices:
            print(d["hostname"], d["ip_address"])
    """
    import duckdb

    if db_path is None:
        from olav.core.config import MAIN_DB_PATH
        db_path = MAIN_DB_PATH

    sql_type = classify_sql(sql)

    if sql_type == "SELECT":
        with duckdb.connect(str(db_path), read_only=True) as conn:
            cur = conn.cursor()
            cur.execute(sql, params or [])
            if cur.description:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
            return []

    if not read_only:
        with open_write_connection(str(db_path)) as conn:
            cur = conn.cursor()
            cur.execute(sql, params or [])
            if cur.description:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
            return [{"rows_affected": cur.rowcount}]

    return [{"requires_approval": True, "sql_type": sql_type, "sql": sql,
             "reason": f"{sql_type} operation requires explicit approval"}]


def get_schema(db_path: str | Path | None = None) -> dict[str, Any]:
    """Return database schema metadata.

    Returns:
        Dict with 'tables' (list of qualified names) and 'table_details'
        (column info per table).
    """
    import duckdb

    if db_path is None:
        from olav.core.config import MAIN_DB_PATH
        db_path = MAIN_DB_PATH

    result: dict[str, Any] = {"tables": [], "table_details": {}}
    try:
        with duckdb.connect(str(db_path), read_only=True) as conn:
            tables = conn.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema NOT IN ('information_schema', 'pg_catalog')"
            ).fetchall()
            for schema, table in tables:
                qualified = f"{schema}.{table}"
                result["tables"].append(qualified)
                try:
                    cols = conn.execute(
                        f"SELECT column_name, data_type FROM information_schema.columns "
                        f"WHERE table_schema='{schema}' AND table_name='{table}'"
                    ).fetchall()
                    result["table_details"][qualified] = {
                        "columns": [{"name": c[0], "type": c[1]} for c in cols]
                    }
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("get_schema failed: %s", exc)
    return result

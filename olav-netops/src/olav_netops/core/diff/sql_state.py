"""SQL state diff helper — compare any table between two snapshots.

Uses DuckDB ``EXCEPT`` to find missing/new rows between snapshots.
Returns only the delta. Called by ``inspect_drift_sql`` (per ADR-0007
R91); not registered as a direct MCP tool.
"""

from __future__ import annotations

import duckdb

from olav.core.config import MAIN_DB_PATH


def _get_table_columns(table_name: str, snapshot_id: str) -> list[str]:
    """Get column names for a table."""
    with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
        try:
            result = conn.execute(f"DESCRIBE {table_name}").fetchall()
            return [r[0] for r in result if r[0] != "snapshot_id"]
        except Exception:
            return []


def _diff_table(table_name: str, snapshot_1: str, snapshot_2: str) -> tuple[list[dict], list[dict]]:
    """Compare table between two snapshots using SQL EXCEPT."""
    with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
        columns = _get_table_columns(table_name, snapshot_1)

        if not columns:
            return [], []

        col_list = ", ".join(columns)

        # Find missing in T2 (in T1 but not in T2)
        missing_query = f"""
            SELECT {col_list}
            FROM {table_name}
            WHERE snapshot_id = ?
            EXCEPT
            SELECT {col_list}
            FROM {table_name}
            WHERE snapshot_id = ?
        """

        try:
            missing_result = conn.execute(missing_query, [snapshot_1, snapshot_2]).fetchall()
            missing = [dict(zip(columns, r)) for r in missing_result]
        except Exception:
            missing = []

        # Find new in T2 (in T2 but not in T1)
        new_query = f"""
            SELECT {col_list}
            FROM {table_name}
            WHERE snapshot_id = ?
            EXCEPT
            SELECT {col_list}
            FROM {table_name}
            WHERE snapshot_id = ?
        """

        try:
            new_result = conn.execute(new_query, [snapshot_2, snapshot_1]).fetchall()
            new = [dict(zip(columns, r)) for r in new_result]
        except Exception:
            new = []

        return missing, new


def diff_sql_state(
    table_name: str,
    snapshot_id_1: str,
    snapshot_id_2: str,
    *,
    row_limit: int = 50,
) -> dict:
    """Compare SQL table state between two snapshots.

    Uses DuckDB ``EXCEPT`` to find delta between snapshots:

    * ``missing_in_t2``: rows in T1 but not in T2
    * ``new_in_t2``: rows in T2 but not in T1

    Args:
        table_name: Table to compare (e.g. ``ospf_neighbors``).
        snapshot_id_1: Baseline / before snapshot ID.
        snapshot_id_2: Target / after snapshot ID.
        row_limit: Cap rows in each list to prevent context overflow
            (default 50). Counts are unaffected.
    """
    try:
        missing, new = _diff_table(table_name, snapshot_id_1, snapshot_id_2)
    except Exception as exc:
        return {"status": "error", "table": table_name, "error": str(exc)}

    return {
        "status": "success",
        "table": table_name,
        "missing_in_t2": missing[:row_limit],
        "new_in_t2": new[:row_limit],
        "total_missing": len(missing),
        "total_new": len(new),
        "message": f"Found {len(missing)} missing, {len(new)} new rows",
    }

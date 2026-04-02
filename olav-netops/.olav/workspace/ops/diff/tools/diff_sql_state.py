#!/usr/bin/env python3
"""
SQL State Diff Tool - Compare any table between two snapshots.

Uses DuckDB EXCEPT to find missing/new rows between snapshots.
Returns only the delta (what was added and what was removed).

Usage:
    diff_sql_state(table_name="ospf_neighbors", snapshot_id_1="20260226_100000", snapshot_id_2="20260226_120000")
"""

import json
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


def _find_project_root() -> Path:
    """Locate project root."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

import duckdb

from olav.core.config import MAIN_DB_PATH


class DiffInput(BaseModel):
    """Input for SQL state diff."""

    table_name: str = Field(..., description="Table to compare")
    snapshot_id_1: str = Field(..., description="Baseline/Before snapshot ID")
    snapshot_id_2: str = Field(..., description="Target/After snapshot ID")


class DiffOutput(BaseModel):
    """Output from SQL state diff."""

    status: str = Field(..., description="success | error")
    table: str = Field(..., description="Table name compared")
    missing_in_t2: list[dict] = Field(default_factory=list, description="Rows in T1 but not T2")
    new_in_t2: list[dict] = Field(default_factory=list, description="Rows in T2 but not T1")
    total_missing: int = Field(default=0, description="Count of missing rows")
    total_new: int = Field(default=0, description="Count of new rows")
    message: str | None = Field(default=None, description="Additional info")
    error: str | None = Field(default=None, description="Error message if status=error")


def _get_table_columns(table_name: str, snapshot_id: str) -> list[str]:
    """Get column names for a table."""
    with duckdb.connect(str(MAIN_DB_PATH)) as conn:
        try:
            result = conn.execute(f"DESCRIBE {table_name}").fetchall()
            return [r[0] for r in result if r[0] != "snapshot_id"]
        except Exception:
            return []


def _diff_table(table_name: str, snapshot_1: str, snapshot_2: str) -> tuple[list[dict], list[dict]]:
    """Compare table between two snapshots using SQL EXCEPT."""
    with duckdb.connect(str(MAIN_DB_PATH)) as conn:
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
            missing = [dict(zip(columns, r, strict=False)) for r in missing_result]
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
            new = [dict(zip(columns, r, strict=False)) for r in new_result]
        except Exception:
            new = []

        return missing, new


def main(params: dict) -> dict:
    """Compare SQL state between two snapshots."""
    try:
        args = DiffInput(**params)
    except Exception as e:
        return DiffOutput(
            status="error",
            table=params.get("table_name", ""),
            error=f"Invalid parameters: {str(e)}",
        ).model_dump(exclude_none=True)

    table_name = args.table_name
    snapshot_1 = args.snapshot_id_1
    snapshot_2 = args.snapshot_id_2

    try:
        missing, new = _diff_table(table_name, snapshot_1, snapshot_2)

        return DiffOutput(
            status="success",
            table=table_name,
            missing_in_t2=missing[:50],  # Limit to prevent context overflow
            new_in_t2=new[:50],
            total_missing=len(missing),
            total_new=len(new),
            message=f"Found {len(missing)} missing, {len(new)} new rows",
        ).model_dump(exclude_none=True)

    except Exception as e:
        return DiffOutput(status="error", table=table_name, error=str(e)).model_dump(
            exclude_none=True
        )


# =============================================================================
# LangChain Tool Registration
# =============================================================================


@tool
def diff_sql_state(table_name: str, snapshot_id_1: str, snapshot_id_2: str) -> dict:
    """Compare SQL table state between two snapshots.

    Uses DuckDB EXCEPT to find delta between snapshots:
    - missing_in_t2: Rows that existed in T1 but not in T2
    - new_in_t2: Rows that exist in T2 but didn't in T1

    Args:
        table_name: Table to compare (e.g., ospf_neighbors, interfaces, routes)
        snapshot_id_1: Baseline/Before snapshot ID
        snapshot_id_2: Target/After snapshot ID

    Returns:
        Dictionary with missing and new rows

    Examples:
        >>> diff_sql_state("ospf_neighbors", "20260226_100000", "20260226_120000")
        >>> diff_sql_state("interfaces", "20260225_000000", "20260226_000000")
    """
    return main(
        {"table_name": table_name, "snapshot_id_1": snapshot_id_1, "snapshot_id_2": snapshot_id_2}
    )


if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        if not input_str:
            input_data = {}
        else:
            input_data = json.loads(input_str)

        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        sys.exit(1)

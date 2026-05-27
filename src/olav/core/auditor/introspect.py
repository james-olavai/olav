"""Query DuckDB / LanceDB schema for audit Profile design.

Returns a structured dict of table names → column lists so the
auditor agent can write correct SQL without hallucinating column
names. Per ADR-0007 + ADR-0008, called from auditor skill
scripts; not registered as an MCP tool.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def database_introspection(
    db_type: str = "duckdb",
    db_path: str | None = None,
    intent: str = "",
) -> dict:
    """Return schema information for the specified database.

    Args:
        db_type: "duckdb" or "lancedb"
        db_path: Path to the database file/directory.
                 Defaults to OLAV project MAIN_DB_PATH / knowledge_db_dir.
        intent:  Optional natural language description of what the designer
                 is looking for (used for logging only).

    Returns:
        For duckdb: {"db_type": "duckdb", "tables": {table_name: {"columns": [col, ...], "sample_rows": [...]}}}
        For lancedb: {"db_type": "lancedb", "tables": {table_name: {"columns": [...]}}}
    """
    db_type = db_type.lower().strip()

    if db_type == "duckdb":
        return _introspect_duckdb(db_path)
    elif db_type == "lancedb":
        return _introspect_lancedb(db_path)
    else:
        raise ValueError(
            f"Unsupported db_type: {db_type!r}. Use 'duckdb' or 'lancedb'."
        )


def _introspect_duckdb(db_path: str | None) -> dict:
    import duckdb

    if db_path is None:
        try:
            from olav.core.config import MAIN_DB_PATH
            db_path = str(MAIN_DB_PATH)
        except ImportError:
            raise ValueError("db_path required when OLAV config is unavailable")

    tables_info: dict = {}
    with duckdb.connect(str(db_path), read_only=True) as conn:
        # Get all user tables (exclude system tables)
        table_rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()

        for (table_name,) in table_rows:
            col_rows = conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [table_name],
            ).fetchall()
            columns = [r[0] for r in col_rows]
            col_types = {r[0]: r[1] for r in col_rows}

            # Fetch up to 2 sample rows for context
            try:
                sample = conn.execute(
                    f'SELECT * FROM "{table_name}" LIMIT 2'
                ).fetchall()
                sample_rows = [dict(zip(columns, row, strict=False)) for row in sample]
            except Exception:
                sample_rows = []

            tables_info[table_name] = {
                "columns": columns,
                "column_types": col_types,
                "sample_rows": sample_rows,
            }

    return {"db_type": "duckdb", "tables": tables_info}


def _introspect_lancedb(db_path: str | None) -> dict:
    try:
        import lancedb  # type: ignore
    except ImportError:
        return {"db_type": "lancedb", "error": "lancedb not installed", "tables": {}}

    if db_path is None:
        try:
            from olav.core.config import get_paths_config
            db_path = str(get_paths_config().knowledge_dir)
        except Exception:
            return {"db_type": "lancedb", "error": "db_path required", "tables": {}}

    tables_info: dict = {}
    try:
        db = lancedb.connect(str(db_path))
        for table_name in db.table_names():
            tbl = db.open_table(table_name)
            schema = tbl.schema
            columns = [field.name for field in schema]
            tables_info[table_name] = {"columns": columns}
    except Exception as exc:
        logger.warning("LanceDB introspection failed: %s", exc)

    return {"db_type": "lancedb", "tables": tables_info}

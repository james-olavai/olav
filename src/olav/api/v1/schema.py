"""Schema Discovery API for DuckDB introspection.

Phase 1.1: Schema-aware API for discovering database schema and accessing data.
This module provides:
- list_tables(): Discover all tables and views
- get_table_schema(): Get schema metadata for a table
- get_sample_data(): Get sample rows from a table
"""

from dataclasses import dataclass
from typing import Any

import duckdb

from config.paths import UNIFIED_DB


@dataclass
class TableSchema:
    """Table schema metadata."""
    name: str
    type: str  # "VIEW" | "BASE TABLE" | "TEMPORARY" | "EXTERNAL"
    columns: list[dict[str, Any]]
    row_count: int
    description: str | None = None


@dataclass
class SchemaDiscoveryResult:
    """Complete database schema discovery result."""
    tables: list[TableSchema]
    views: list[TableSchema]
    total_tables: int
    total_views: int


def list_tables() -> SchemaDiscoveryResult:
    """Discover all tables and views from DuckDB.
    
    Returns:
        SchemaDiscoveryResult containing tables and views
    
    Example:
        >>> result = list_tables()
        >>> print(result.total_tables)
        5
        >>> [t.name for t in result.tables]
        ['devices', 'interfaces', ...]
    """
    conn = duckdb.connect(str(UNIFIED_DB), read_only=True)

    # Query information_schema for all tables and views
    tables_query = """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
    """

    tables = []
    views = []

    try:
        for row in conn.execute(tables_query).fetchall():
            table_name, table_type = row

            # Get columns for this table
            columns_query = f"""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = '{table_name}'
                ORDER BY ordinal_position
            """
            columns = []
            for col_row in conn.execute(columns_query).fetchall():
                col_name, dtype, nullable = col_row
                columns.append({
                    "name": col_name,
                    "type": dtype,
                    "nullable": nullable == "YES"
                })

            # Get row count
            try:
                count_query = f"SELECT COUNT(*) FROM {table_name}"
                row_count = conn.execute(count_query).fetchone()[0]
            except Exception:
                row_count = 0

            schema = TableSchema(
                name=table_name,
                type=table_type,
                columns=columns,
                row_count=row_count,
                description=None
            )

            # Categorize as table or view
            if table_type == "VIEW":
                views.append(schema)
            else:
                tables.append(schema)
    finally:
        conn.close()

    return SchemaDiscoveryResult(
        tables=tables,
        views=views,
        total_tables=len(tables),
        total_views=len(views)
    )


def get_table_schema(table_name: str) -> TableSchema:
    """Get schema for specific table or view.
    
    Args:
        table_name: Name of table or view
    
    Returns:
        TableSchema with column information
    
    Raises:
        ValueError: If table doesn't exist
    
    Example:
        >>> schema = get_table_schema("devices")
        >>> schema.name
        'devices'
        >>> len(schema.columns)
        8
    """
    schema = list_tables()

    # Search in both tables and views
    for table in schema.tables + schema.views:
        if table.name == table_name:
            return table

    raise ValueError(f"Table not found: {table_name}")


def get_sample_data(
    table_name: str,
    limit: int = 10
) -> list[dict[str, Any]]:
    """Get sample rows from table.
    
    Args:
        table_name: Table or view name
        limit: Maximum number of rows to return
    
    Returns:
        List of row dictionaries
    
    Raises:
        ValueError: If table doesn't exist
    
    Example:
        >>> rows = get_sample_data("devices", limit=5)
        >>> len(rows)
        5
        >>> rows[0].keys()
        dict_keys(['name', 'hostname', 'platform', ...])
    """
    # Validate table exists first
    get_table_schema(table_name)

    conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
    try:
        query = f"SELECT * FROM {table_name} LIMIT {limit}"
        result = conn.execute(query).fetchall()

        # Get column names
        columns_query = f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = '{table_name}'
            ORDER BY ordinal_position
        """
        col_names = [row[0] for row in conn.execute(columns_query).fetchall()]

        # Convert to list of dicts
        rows = [dict(zip(col_names, row)) for row in result]
        return rows
    finally:
        conn.close()

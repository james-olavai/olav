"""Phase 1.2: Data Access API with SQL injection prevention.

This module provides safe, parameterized query building and execution.
Security-first design ensures SQL injection is impossible.

Key Features:
- Parameterized WHERE clause (no string concatenation)
- Column name validation against schema
- Table name validation against schema
- Read-only database connections
- Type-safe result handling
"""

from dataclasses import dataclass
from typing import Any

import duckdb

from config.paths import UNIFIED_DB
from olav.api.v1.schema import get_table_schema, list_tables


@dataclass
class SafeQuery:
    """Parameterized SQL query with separation of SQL and parameters.
    
    This design ensures SQL injection is impossible because values
    are never concatenated into the SQL string.
    
    Attributes:
        sql: SQL query with ? placeholders (never contains user values)
        params: List of user values (separate from SQL)
        table: Table name being queried
    """
    sql: str
    params: list
    table: str


@dataclass
class QueryResult:
    """Result of a query execution.
    
    Attributes:
        table: Table name queried
        rows: List of dicts, one per row
        total_count: Total rows matching WHERE (ignoring LIMIT/OFFSET)
        columns: List of column names returned
        query_sql: Original query SQL (for debugging)
    """
    table: str
    rows: list[dict[str, Any]]
    total_count: int
    columns: list[str]
    query_sql: str


def _validate_table_exists(table_name: str) -> None:
    """Validate that table exists in database.
    
    Args:
        table_name: Table or view name to validate
        
    Raises:
        ValueError: If table does not exist
    """
    schema_result = list_tables()

    all_tables = schema_result.tables + schema_result.views
    table_names = [t.name.lower() for t in all_tables]

    if table_name.lower() not in table_names:
        raise ValueError(f"Table '{table_name}' does not exist")


def _validate_column_exists(table_name: str, column_name: str) -> None:
    """Validate that column exists in table.
    
    Args:
        table_name: Table name
        column_name: Column name to validate
        
    Raises:
        ValueError: If column does not exist in table
    """
    schema = get_table_schema(table_name)
    column_names = [col["name"].lower() for col in schema.columns]

    if column_name.lower() not in column_names:
        raise ValueError(f"Invalid column: '{column_name}'")


def build_query(
    table_name: str,
    where: dict[str, Any] | None = None,
    order_by: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> SafeQuery:
    """Build parameterized SQL query with security validation.
    
    Security Features:
    1. Table name validation (checked against schema)
    2. Column name validation (WHERE and ORDER BY)
    3. Parameter binding (WHERE values in separate params list)
    4. No string concatenation of user values
    
    Args:
        table_name: Table or view name (validated)
        where: Column filters as {column: value} dict (parameterized)
        order_by: Column name to sort by (validated)
        limit: Max rows to return (default 100)
        offset: Pagination offset (default 0)
        
    Returns:
        SafeQuery with SQL and parameters separated
        
    Raises:
        ValueError: If table doesn't exist or column is invalid
        
    Example:
        >>> query = build_query(
        ...     "devices",
        ...     where={"platform": "cisco_ios"},
        ...     order_by="name",
        ...     limit=10
        ... )
        >>> query.sql
        "SELECT * FROM devices WHERE platform = ? ORDER BY name LIMIT ? OFFSET ?"
        >>> query.params
        ["cisco_ios", 10, 0]
    """
    # 1. Validate table exists
    _validate_table_exists(table_name)

    # Get schema for column validation
    schema = get_table_schema(table_name)
    column_names = [col["name"].lower() for col in schema.columns]

    # 2. Build SELECT clause (no user input)
    sql = f"SELECT * FROM {table_name}"
    params = []

    # 3. Build WHERE clause with parameterization
    if where:
        conditions = []

        for column, value in where.items():
            # Validate column exists
            if column.lower() not in column_names:
                raise ValueError(f"Invalid column: '{column}'")

            # Build parameterized condition (? instead of value)
            conditions.append(f"{column} = ?")
            params.append(value)

        # Combine conditions with AND
        sql += " WHERE " + " AND ".join(conditions)

    # 4. Build ORDER BY clause (column name only, no user values)
    if order_by:
        # Validate column exists
        if order_by.lower() not in column_names:
            raise ValueError(f"Invalid order_by column: '{order_by}'")

        sql += f" ORDER BY {order_by}"

    # 5. Add pagination with parameterization
    sql += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    return SafeQuery(sql=sql, params=params, table=table_name)


def query_table(
    table_name: str,
    where: dict[str, Any] | None = None,
    order_by: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> QueryResult:
    """Execute safe parameterized query against table.
    
    This function builds a parameterized query and executes it safely.
    SQL injection is prevented through parameter binding.
    
    Args:
        table_name: Table or view name
        where: Column filters (parameterized)
        order_by: Column to sort by
        limit: Max rows to return
        offset: Pagination offset
        
    Returns:
        QueryResult with rows, total_count, and columns
        
    Raises:
        ValueError: If table or column is invalid
        
    Example:
        >>> result = query_table(
        ...     "devices",
        ...     where={"vendor": "cisco"},
        ...     limit=10
        ... )
        >>> len(result.rows)
        10
        >>> result.total_count
        45
    """
    # Build parameterized query
    safe_query = build_query(table_name, where, order_by, limit, offset)

    # Execute query with DuckDB (parameters are bound safely)
    conn = duckdb.connect(str(UNIFIED_DB), read_only=True)

    try:
        # Execute main query using native DuckDB (no pandas dependency)
        result = conn.execute(safe_query.sql, safe_query.params)

        # Get columns from description
        columns = [desc[0] for desc in result.description]

        # Fetch all rows as tuples
        all_rows = result.fetchall()

        # Convert tuples to dicts
        rows = [dict(zip(columns, row)) for row in all_rows]

        # Get total count (without LIMIT/OFFSET)
        count_sql = f"SELECT COUNT(*) FROM {table_name}"
        count_params = []

        if where:
            conditions = []
            for column, value in where.items():
                conditions.append(f"{column} = ?")
                count_params.append(value)
            count_sql += " WHERE " + " AND ".join(conditions)

        total_count = conn.execute(count_sql, count_params).fetchone()[0]

        return QueryResult(
            table=table_name,
            rows=rows,
            total_count=total_count,
            columns=columns,
            query_sql=safe_query.sql,
        )

    finally:
        conn.close()

#!/usr/bin/env python3
"""
Database Tool - Intelligent SQL query execution with auto schema exploration.

Core Features:
1. Auto schema discovery (no manual inspect_schema calls)
2. SQL generation with context
3. Error self-correction (via Agent ReAct loop)
4. DuckDB-specific optimizations
5. SchemaContext singleton caching (5 min TTL)

Usage in DeepAgents:
    from .tools import execute_sql
    agent = create_deep_agent(tools=[execute_sql.execute_sql])
"""

import json
import sys
import time
from datetime import date, datetime
from datetime import time as time_type
from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field, validator
from tenacity import retry, stop_after_attempt, wait_exponential


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

from olav.core.config import MAIN_DB_PATH


def db_query(sql: str, params: list | None = None) -> list[dict]:
    """Execute a SQL query against the main DuckDB database (read-only)."""
    with _duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
    """Execute a SQL query against the main DuckDB database."""
    with _duckdb.connect(str(MAIN_DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if cur.description:
            cols = [d[0] for d in cur.description]
            result = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
            return result
        return []




# ============================================================================
# Pydantic Models for Type-Safe Parameter Validation
# ============================================================================


class DatabaseQueryInput(BaseModel):
    """Database query input parameters - type-safe validation"""

    query: str = Field(default="", description="Natural language query")
    sql: str = Field(default="", description="Direct SQL query (optional)")
    explain_only: bool = Field(
        default=False, description="Return only schema context without executing query"
    )

    @validator("query", "sql", pre=True)
    def validate_not_none(cls, v):
        """Convert None to empty string"""
        if v is None:
            return ""
        return v


class DatabaseQueryOutput(BaseModel):
    """Database query output format - unified response"""

    data: list[dict] | None = Field(default=None, description="Query results")
    table: str | None = Field(
        default=None, description="Markdown table representation (for small results)"
    )
    schema_context: str | None = Field(default=None, description="Database schema information")
    sql: str | None = Field(default=None, description="SQL query executed")
    count: int | None = Field(default=None, description="Number of results")
    status: str = Field(..., description="success | error | needs_sql_generation")
    error: str | None = Field(default=None, description="Error message if status=error")
    error_type: str | None = Field(default=None, description="Type of error")
    message: str | None = Field(default=None, description="Additional message")
    user_query: str | None = Field(default=None, description="Original user query")
    tables: list[str] | None = Field(default=None, description="Available tables")
    attempted_sql: str | None = Field(default=None, description="SQL that failed")
    suggestions: list[str] | None = Field(default=None, description="Suggestions for retry when count=0")


class SchemaContext:
    """Context manager for auto-schema exploration with singleton caching.

    Uses singleton pattern to cache schema across multiple execute_sql calls.
    Cache TTL is 5 minutes by default.
    """

    _instance: "SchemaContext | None" = None
    _last_refresh: float = 0
    _cache_ttl: float = 300.0  # 5 minutes TTL

    def __new__(cls) -> "SchemaContext":
        """Singleton pattern - reuse instance if cache is valid."""
        now = time.time()
        if cls._instance is None or (now - cls._last_refresh) > cls._cache_ttl:
            cls._instance = super().__new__(cls)
            cls._instance._schema_cache: dict[str, Any] = {}
            cls._instance._refresh_schema()
            cls._last_refresh = now
        return cls._instance

    def __init__(self):
        """Initialize with automatic schema caching."""
        # Schema already initialized in __new__
        pass

    def _refresh_schema(self) -> None:
        """Refresh schema cache by querying INFORMATION_SCHEMA."""
        try:
            # Get all tables
            tables_result = db_query(
                """
                SELECT table_name, table_type 
                FROM information_schema.tables 
                WHERE table_schema = 'main' 
                ORDER BY table_name
                """
            )

            self._schema_cache["tables"] = [row["table_name"] for row in tables_result]
            self._schema_cache["table_details"] = {}

            # Get columns for each table
            for table_name in self._schema_cache["tables"]:
                try:
                    columns_result = db_query(f"DESCRIBE {table_name}")
                    self._schema_cache["table_details"][table_name] = {
                        "columns": [
                            {
                                "name": row.get("column_name", row.get("Field", "")),
                                "type": row.get("column_type", row.get("Type", "")),
                            }
                            for row in columns_result
                        ]
                    }
                except Exception:
                    # Skip tables with errors
                    pass

            # Get sample data for top tables (for context)
            self._schema_cache["samples"] = {}
            for table_name in self._schema_cache["tables"][:5]:  # Top 5 tables only
                try:
                    sample = db_query(f"SELECT * FROM {table_name} LIMIT 3")
                    if sample:
                        self._schema_cache["samples"][table_name] = sample
                except Exception:
                    pass

            # Query schema_catalog for parsed_outputs JSON field info
            # Enables LLM to generate: SELECT parsed_data->>'field' FROM parsed_outputs
            try:
                catalog_rows = db_query(
                    "SELECT source_name, platform, fields FROM schema_catalog "
                    "WHERE source_type = 'textfsm' ORDER BY source_name, platform"
                )
                if catalog_rows:
                    schema_catalog_info: list[str] = []
                    for row in catalog_rows:
                        fields = row.get("fields", [])
                        if isinstance(fields, str):
                            try:
                                fields = json.loads(fields)
                            except Exception:
                                fields = []
                        field_names = [f["name"] for f in (fields or []) if isinstance(f, dict)]
                        if field_names:
                            schema_catalog_info.append(
                                f"  {row['source_name']} ({row['platform']}): "
                                + ", ".join(field_names)
                            )
                    self._schema_cache["schema_catalog"] = schema_catalog_info
            except Exception:
                pass  # schema_catalog not yet populated, skip silently

        except Exception as e:
            self._schema_cache = {"error": str(e)}

    def get_schema_context(self) -> str:
        """Get formatted schema context for LLM."""
        if "error" in self._schema_cache:
            return f"Schema error: {self._schema_cache['error']}"

        context_parts = ["**Available Database Schema:**\n"]

        # List tables
        context_parts.append(f"Tables: {', '.join(self._schema_cache['tables'])}\n")

        # Detail each table
        for table_name, details in self._schema_cache["table_details"].items():
            context_parts.append(f"\n**{table_name}:**")
            columns = [f"  - {col['name']}: {col['type']}" for col in details["columns"]]
            context_parts.append("\n".join(columns))

            # Add sample if available
            if table_name in self._schema_cache.get("samples", {}):
                sample = self._schema_cache["samples"][table_name]
                if sample:
                    context_parts.append(f"  Sample: {sample[0]}")

        # Add schema_catalog block (JSON fields for parsed_outputs)
        schema_catalog = self._schema_cache.get("schema_catalog", [])
        if schema_catalog:
            context_parts.append("\n**parsed_outputs JSON fields (via schema_catalog):**")
            context_parts.append(
                "  Query pattern: SELECT parsed_data->>'field_name' "
                "FROM parsed_outputs WHERE command='...' AND snapshot_date=CURRENT_DATE"
            )
            context_parts.extend(schema_catalog[:50])  # cap at 50 entries

        return "\n".join(context_parts)

    def query(self, sql: str) -> list[dict]:
        """Execute SQL query with error details."""
        return db_query(sql)


def _sanitize_value(val: Any) -> Any:
    """Convert non-JSON-serializable types to strings."""
    if isinstance(val, (datetime, date, time_type)):
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
    """Execute database query with auto schema exploration.

    Args:
        params: {
            "query": "Natural language query",
            "sql": "Optional direct SQL",
            "explain_only": Optional bool to only return schema context
        }

    Returns:
        {
            "data": [...],
            "sql": "Executed SQL",
            "schema_context": "Auto-discovered schema",
            "status": "success"|"error"
        }
    """
    # Validate parameters with Pydantic
    try:
        args = DatabaseQueryInput(**params)
    except Exception as e:
        output = DatabaseQueryOutput(
            status="error", error=f"Invalid parameters: {str(e)}", error_type="validation_error"
        )
        return output.model_dump(exclude_none=True)

    user_query = args.query
    direct_sql = args.sql
    explain_only = args.explain_only

    # Get schema context (singleton, cached for 5 min)
    context = SchemaContext()
    schema_context = context.get_schema_context()

    # If explain_only, return just schema
    if explain_only:
        output = DatabaseQueryOutput(
            schema_context=schema_context,
            tables=context._schema_cache.get("tables", []),
            status="success",
        )
        return output.model_dump(exclude_none=True)

    # If direct SQL provided (agent already generated it), execute it
    if direct_sql:
        try:
            # Execute query (LangGraph cache handles caching at framework level)
            results = context.query(direct_sql)
            results = _sanitize_rows(results)

            # Limit data returned to Agent context to prevent bloat/hang (max 20 rows)
            # Full data is still exported to CSV if count > 50
            MAX_ROWS_TO_CONTEXT = 20
            
            # Auto-export logic
            csv_path = None
            if len(results) > 50:
                import csv
                from pathlib import Path

                export_dir = Path("exports")
                export_dir.mkdir(exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                csv_path = export_dir / f"query_{timestamp}.csv"

                with open(csv_path, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=results[0].keys())
                    writer.writeheader()
                    writer.writerows(results)

            # Prepare data for LLM context
            truncated = len(results) > MAX_ROWS_TO_CONTEXT
            display_data = results[:MAX_ROWS_TO_CONTEXT] if truncated else results

            message = None
            if csv_path:
                message = f"FULL results ({len(results)} rows) exported to {csv_path}."
            if truncated:
                msg = f"Only first {MAX_ROWS_TO_CONTEXT} rows returned to context to prevent bloat."
                message = f"{message} {msg}" if message else msg

            # Check if results are empty - provide schema hints for agentic retry
            if len(results) == 0:
                # ... same as before ...
                output = DatabaseQueryOutput(
                    data=results,
                    sql=direct_sql,
                    count=0,
                    status="empty",
                    message="Query returned 0 results. Schema context provided for retry.",
                    schema_context=schema_context,
                )
                return output.model_dump(exclude_none=True)

            output = DatabaseQueryOutput(
                data=display_data,
                sql=direct_sql,
                count=len(results),
                status="success",
                message=message,
            )
            return output.model_dump(exclude_none=True)
        except Exception as e:
            # Return error with schema context for agent to retry
            output = DatabaseQueryOutput(
                error=str(e),
                schema_context=schema_context,
                attempted_sql=direct_sql,
                status="error",
                error_type="execution_error",
            )
            return output.model_dump(exclude_none=True)

    # If natural language query, return schema context for agent to generate SQL
    output = DatabaseQueryOutput(
        message="Schema context provided for SQL generation",
        user_query=user_query,
        schema_context=schema_context,
        status="needs_sql_generation",
    )
    return output.model_dump(exclude_none=True)


# ============================================================================
# LangChain Tool Registration
# ============================================================================


@tool
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def execute_sql(query: str = "", sql: str = "", explain_only: bool = False) -> dict:
    """Execute SQL query with automatic schema discovery and error correction.
    ⭐ DEFAULT TOOL for device queries. Use this FIRST before execute_cli.

    WHEN TO USE:
    - Device inventory, counts, lists → SELECT * FROM devices
    - Interface status, IPs → SELECT * FROM parsed_outputs WHERE command='show ip interface brief'
    - Topology links → SELECT * FROM topology_links
    - Any data that exists in the database

    Features:
    - Automatic schema context discovery (cached for 5 min)
    - SQL generation guidance for the LLM
    - Error self-correction support
    - DuckDB-specific optimizations

    Args:
        query: Natural language question about the database
        sql: Optional direct SQL query (used for executing generated SQL)
        explain_only: If True, return only schema context

    Returns:
        Status, results, or error information with schema context

    Examples:
        Example 1 - Get device count:
        >>> execute_sql(sql="SELECT COUNT(*) FROM devices")

        Example 2 - List all devices:
        >>> execute_sql(sql="SELECT name, hostname, platform FROM devices")

        Example 3 - Get schema for SQL generation:
        >>> execute_sql(explain_only=True)
    """
    params = {"query": query, "sql": sql, "explain_only": explain_only}
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
            json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False),
            file=sys.stderr,
        )
        sys.exit(1)

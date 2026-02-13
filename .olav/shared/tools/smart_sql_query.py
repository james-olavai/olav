#!/usr/bin/env python3
"""
Smart SQL Query - Intelligent database query tool with auto schema exploration.

Inspired by LangChain SQL Agent but lightweight and integrated with DeepAgents.

Key Features (borrowed from LangChain SQL Agent):
1. Auto schema discovery (no manual inspect_schema calls)
2. SQL generation with context
3. Error self-correction (via ReAct loop in agent)
4. DuckDB-specific optimizations

This tool replaces the query_database + inspect_schema manual workflow.

Usage:
    echo '{"query": "有多少个设备?"}' | python3 smart_sql_query.py
"""

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, validator
from langchain_core.tools import tool
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

from olav.lib.data_gateway import query_database as db_query


# ============================================================================
# Pydantic Models for Type-Safe Parameter Validation
# ============================================================================

class SmartSQLInput(BaseModel):
    """Smart SQL 查询输入参数 - 使用 Pydantic 自动验证"""
    query: str = Field(default="", description="Natural language query")
    sql: str = Field(default="", description="Direct SQL query (optional)")
    explain_only: bool = Field(
        default=False,
        description="Return only schema context without executing query"
    )
    
    @validator('query', 'sql', pre=True)
    def validate_not_none(cls, v):
        """Convert None to empty string"""
        if v is None:
            return ""
        return v


class SmartSQLOutput(BaseModel):
    """Smart SQL 查询输出格式 - 统一返回格式"""
    data: list[dict] | None = Field(default=None, description="Query results")
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


class SmartSQLContext:

    """Context manager for auto-schema exploration (inspired by LangChain SQLDatabase)."""

    def __init__(self):
        """Initialize with automatic schema caching."""
        self._schema_cache: dict[str, Any] = {}
        self._refresh_schema()

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
                except Exception as e:
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

        except Exception as e:
            self._schema_cache = {"error": str(e)}

    def get_schema_context(self) -> str:
        """Get formatted schema context for LLM (like LangChain's get_table_info)."""
        if "error" in self._schema_cache:
            return f"Schema error: {self._schema_cache['error']}"

        context_parts = ["**Available Database Schema:**\n"]

        # List tables
        context_parts.append(f"Tables: {', '.join(self._schema_cache['tables'])}\n")

        # Detail each table
        for table_name, details in self._schema_cache["table_details"].items():
            context_parts.append(f"\n**{table_name}:**")
            columns = [
                f"  - {col['name']}: {col['type']}" for col in details["columns"]
            ]
            context_parts.append("\n".join(columns))

            # Add sample if available
            if table_name in self._schema_cache.get("samples", {}):
                sample = self._schema_cache["samples"][table_name]
                if sample:
                    context_parts.append(f"  Sample: {sample[0]}")

        return "\n".join(context_parts)

    def query(self, sql: str) -> list[dict]:
        """Execute SQL query with error details."""
        return db_query(sql)


def main(params: dict) -> dict:
    """Smart SQL query with auto schema exploration.

    Args:
        params: {
            "query": "Natural language query",
            "sql": "Optional direct SQL (for agent-generated SQL)",
            "explain_only": Optional bool to only return schema context
        }

    Returns:
        {
            "data": [...],
            "sql": "Generated SQL",
            "schema_context": "Auto-discovered schema",
            "status": "success"|"error"
        }
    """
    # ========== STEP 1: Validate parameters with Pydantic ==========
    try:
        args = SmartSQLInput(**params)
    except Exception as e:
        # Validation error - return immediately
        output = SmartSQLOutput(
            status="error",
            error=f"Invalid parameters: {str(e)}",
            error_type="validation_error"
        )
        return output.model_dump(exclude_none=True)
    
    user_query = args.query
    direct_sql = args.sql
    explain_only = args.explain_only

    # Initialize schema context
    context = SmartSQLContext()
    schema_context = context.get_schema_context()

    # If explain_only, return just schema
    if explain_only:
        output = SmartSQLOutput(
            schema_context=schema_context,
            tables=context._schema_cache.get("tables", []),
            status="success"
        )
        return output.model_dump(exclude_none=True)

    # If direct SQL provided (agent already generated it), execute it
    if direct_sql:
        try:
            results = context.query(direct_sql)
            output = SmartSQLOutput(
                data=results,
                sql=direct_sql,
                count=len(results),
                status="success"
            )
            return output.model_dump(exclude_none=True)
        except Exception as e:
            # Return error with schema context for agent to retry
            output = SmartSQLOutput(
                error=str(e),
                schema_context=schema_context,
                attempted_sql=direct_sql,
                status="error",
                error_type="execution_error"
            )
            return output.model_dump(exclude_none=True)

    # If natural language query, return schema context for agent to generate SQL
    # (The agent's ReAct loop will use this to generate SQL)
    output = SmartSQLOutput(
        message="Schema context provided for SQL generation",
        user_query=user_query,
        schema_context=schema_context,
        status="needs_sql_generation"
    )
    return output.model_dump(exclude_none=True)


# ============================================================================
# LangChain Tool Registration (for DeepAgents integration)
# ============================================================================

@tool
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def smart_sql_query(query: str = "", sql: str = "", explain_only: bool = False) -> dict:
    """Smart SQL query with automatic schema discovery and error correction.
    
    This tool provides:
    - Automatic schema context discovery (no manual inspect_schema calls)
    - SQL generation guidance for the LLM
    - Error self-correction support (via agent ReAct loop)
    - DuckDB-specific optimizations
    
    Args:
        query: Natural language question about the database
        sql: Optional direct SQL query (used by agent for executing generated SQL)
        explain_only: If True, return only schema context without executing anything
    
    Returns:
        Status and results or error information with schema context
    
    Examples:
        Example 1 - Natural language query (agent generates SQL):
        >>> smart_sql_query("How many devices do we have?")
        Returns schema context for agent to generate SQL
        
        Example 2 - Execute generated SQL:
        >>> smart_sql_query(sql="SELECT COUNT(*) FROM devices")
        Returns query results
        
        Example 3 - Get schema only:
        >>> smart_sql_query(explain_only=True)
        Returns database schema information
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

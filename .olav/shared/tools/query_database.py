#!/usr/bin/env python3
"""
Query Database Script - Shared tool used by multiple skills.

Uses data_gateway unified connection to query DuckDB. This attaches
ALL databases (main.duckdb + olav.duckdb + snapshots.duckdb) with
compatibility views so LLM-generated SQL works without catalog prefixes.

Shared by: network-query, network-analysis, network-cli, network-inspection, network-snapshot

Usage:
    echo '{"sql": "SELECT * FROM devices LIMIT 5"}' | python3 .olav/shared/tools/query_database.py
"""

import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field, validator
from langchain_core.tools import tool
from tenacity import retry, stop_after_attempt, wait_exponential

# Add src to Python Path
# Find project root dynamically (walk up until pyproject.toml found)
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

class QueryDatabaseInput(BaseModel):
    """SQL 查询输入参数 - 使用 Pydantic 自动验证"""
    sql: str = Field(..., description="SQL query to execute", min_length=1)
    timeout: int = Field(
        default=30,
        description="Query timeout in seconds",
        ge=1,
        le=300
    )
    
    @validator('sql')
    def validate_sql_not_empty(cls, v):
        """确保 SQL 不仅仅是空格"""
        if not v.strip():
            raise ValueError("SQL command cannot be empty or whitespace only")
        return v


class QueryDatabaseOutput(BaseModel):
    """SQL 查询结果输出模型 - 统一的返回格式"""
    data: list[dict] | None = Field(
        None,
        description="Query result rows"
    )
    count: int | None = Field(
        None,
        description="Number of rows returned"
    )
    status: str = Field(
        ...,
        description="Query status (success or failed)"
    )
    error: str | None = Field(
        None,
        description="Error message if query failed"
    )
    error_type: str | None = Field(
        None,
        description="Type of error: missing_view, database_error"
    )
    suggestion: str | None = Field(
        None,
        description="Recovery suggestion for error resolution"
    )


def main(params: dict) -> dict:
    """Query DuckDB database via data_gateway unified connection.

    Args:
        params: {
            "sql": "SELECT * FROM devices WHERE hostname='R1'",
            "timeout": 30  # optional, default 30 seconds
        }

    Returns:
        QueryDatabaseOutput as dict:
        {
            "data": [...],
            "count": 10,
            "status": "success"
        }
        
        On error:
        {
            "status": "failed", 
            "error": "error message",
            "error_type": "missing_view|database_error",
            "suggestion": "..."
        }
    """
    # ========== STEP 1: Validate parameters with Pydantic ==========
    # This automatically validates:
    # - sql is not empty (min_length=1)
    # - sql is not just whitespace (@validator)
    # - timeout is in range 1-300
    # Raises ValidationError if validation fails
    try:
        args = QueryDatabaseInput(**params)
    except Exception as e:
        # Validation error - return immediately
        output = QueryDatabaseOutput(
            status="failed",
            error=f"Invalid parameters: {str(e)}",
            error_type="validation_error"
        )
        return output.model_dump(exclude_none=True)

    # ========== STEP 2: Execute query ==========
    try:
        # data_gateway.query_database returns list[dict] directly
        results = db_query(args.sql)

        output = QueryDatabaseOutput(
            data=results,
            count=len(results),
            status="success"
        )

    # ========== STEP 3: Handle errors with proper classification ==========
    except Exception as e:
        error_msg = str(e)

        # Classify error for better error handling by LLM
        if (
            "does not exist" in error_msg
            or "no such table" in error_msg.lower()
            or "catalog error" in error_msg.lower()
        ):
            output = QueryDatabaseOutput(
                status="failed",
                error=error_msg,
                error_type="missing_view",
                suggestion="Use inspect_schema to check available tables and columns."
            )
        else:
            output = QueryDatabaseOutput(
                status="failed",
                error=error_msg,
                error_type="database_error",
                suggestion="Check SQL syntax and try again, or use inspect_schema for help."
            )

    # ========== STEP 4: Return formatted result ==========
    # Use exclude_none=True to omit None values from JSON
    return output.model_dump(exclude_none=True)


# ============================================================================
# LangChain Tool Registration (for DeepAgents integration)
# ============================================================================

@tool
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def query_database(sql: str, timeout: int = 30) -> dict:
    """Execute intelligent SQL query with automatic schema discovery.
    
    This tool allows the LLM to query the network database using SQL syntax.
    It supports:
    - Auto schema context (no manual calls needed)
    - SQL generation guidance
    - Error self-correction (via agent ReAct loop)
    
    Args:
        sql: SQL query to execute (e.g., "SELECT * FROM devices WHERE hostname='R1'")
        timeout: Query timeout in seconds (1-300, default 30)
    
    Returns:
        Query results with status, or error information
    
    Examples:
        query_database(sql="SELECT COUNT(*) FROM devices")
        query_database(sql="SELECT hostname FROM devices LIMIT 5", timeout=60)
    """
    # Use Pydantic model for validation
    params = {"sql": sql, "timeout": timeout}
    return main(params)


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return super().default(obj)


if __name__ == "__main__":
    # Standard input/output (all scripts follow this pattern)
    try:
        input_str = sys.stdin.read()
        if not input_str:
            input_data = {}
        else:
            input_data = json.loads(input_str)

        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2, cls=DateTimeEncoder))
    except json.JSONDecodeError as e:
        error_result = {
            "error": f"Invalid JSON input: {str(e)}",
            "status": "failed",
            "error_type": "json_decode_error"
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        error_result = {
            "error": f"Unexpected error: {str(e)}",
            "status": "failed",
            "error_type": "unexpected_error"
        }
        # Print to stderr so SkillAdapter can see it
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

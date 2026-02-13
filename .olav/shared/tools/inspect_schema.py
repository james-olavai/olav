#!/usr/bin/env python3
"""
Inspect Schema - Shared tool used by multiple skills.

Schema introspection for SQL Agent - uses data_gateway unified connection.

Shared by: network-query, network-inspection, network-snapshot

Usage:
    echo '{"table_name": "devices"}' | python3 inspect_schema.py
    echo '{}' | python3 inspect_schema.py
"""

import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field
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

class InspectSchemaInput(BaseModel):
    """Inspect schema 输入参数 - 表名是可选的"""
    table_name: str | None = Field(
        None,
        description="Specific table to inspect (optional, lists all if not provided)",
        max_length=100
    )


class InspectSchemaTableOutput(BaseModel):
    """单表的详细检查结果"""
    table: str = Field(..., description="Table name")
    columns: list[str] = Field(..., description="Column names")
    status: str = Field(..., description="Operation status")
    error: str | None = Field(None, description="Error message if failed")


class InspectSchemaAllTablesOutput(BaseModel):
    """所有表的列表"""
    tables: list[str] = Field(..., description="All table names")
    status: str = Field(..., description="Operation status")
    error: str | None = Field(None, description="Error message if failed")


def main(params: dict) -> dict:
    """Introspection for SQL Agent - list tables or inspect specific table schema."""
    # ========== STEP 1: Validate parameters with Pydantic ==========
    try:
        args = InspectSchemaInput(**params)
    except Exception as e:
        return {
            "status": "failed",
            "error": f"Invalid parameters: {str(e)}"
        }

    # ========== STEP 2: Handle specific table inspection ==========
    if args.table_name:
        try:
            result = db_query(f"DESCRIBE {args.table_name}")
            columns = [row.get("column_name", row.get("Field", "")) for row in result]
            
            output = InspectSchemaTableOutput(
                table=args.table_name,
                columns=columns,
                status="success"
            )
            return output.model_dump(exclude_none=True)
        except Exception as e:
            output = InspectSchemaTableOutput(
                table=args.table_name,
                columns=[],
                status="failed",
                error=f"Failed to inspect table: {str(e)}"
            )
            return output.model_dump(exclude_none=True)
    
    # ========== STEP 3: Handle listing all tables ==========
    else:
        try:
            result = db_query(
                "SELECT DISTINCT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            )
            tables = [row["table_name"] for row in result]
            
            output = InspectSchemaAllTablesOutput(
                tables=tables,
                status="success"
            )
            return output.model_dump(exclude_none=True)
        except Exception as e:
            output = InspectSchemaAllTablesOutput(
                tables=[],
                status="failed",
                error=f"Failed to list tables: {str(e)}"
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
def inspect_schema(table_name: str | None = None) -> dict:
    """Inspect database schema - list tables or columns of specific table.
    
    This tool provides schema introspection for SQL Agent integration.
    If no table is specified, lists all available tables.
    If table is specified, returns columns for that table.
    
    Args:
        table_name: Optional specific table to inspect (e.g., "devices", "interfaces")
    
    Returns:
        Either list of all tables, or detailed schema of specified table
    
    Examples:
        inspect_schema()  # List all tables
        inspect_schema(table_name="devices")  # Show columns of devices table
    """
    # Use Pydantic model for validation
    params = {"table_name": table_name}
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
        print(json.dumps(result, ensure_ascii=False, cls=DateTimeEncoder))
    except json.JSONDecodeError as e:
        error_result = {
            "status": "failed",
            "error": f"Invalid JSON input: {str(e)}"
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        error_result = {
            "status": "failed",
            "error": f"Unexpected error: {str(e)}"
        }
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

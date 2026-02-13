#!/usr/bin/env python3
"""
Discover Data - Shared tool used by multiple skills.

Explores available data in the network database.
Lists tables, views, row counts, and sample data to help LLM understand
what data is available for querying.

Shared by: network-query, network-inspection, network-snapshot

Usage:
    echo '{"pattern": "device"}' | python3 discover_data.py
    echo '{}' | python3 discover_data.py
"""

import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from langchain_core.tools import tool
from tenacity import retry, stop_after_attempt, wait_exponential


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

class DiscoverDataInput(BaseModel):
    """Discover data 输入参数 - pattern 是可选的"""
    pattern: str | None = Field(
        None,
        description="Optional pattern to filter tables (case-insensitive substring match)",
        max_length=100
    )


class TableInfo(BaseModel):
    """单个表的统计信息"""
    table: str = Field(..., description="Table name")
    row_count: int = Field(..., description="Number of rows (-1 if error)")


class DiscoverDataOutput(BaseModel):
    """Discover data 结果输出模型 - 统一的返回格式"""
    tables: list[TableInfo] = Field(..., description="List of tables with row counts")
    summary: str = Field(..., description="Human-readable summary of findings")
    status: str = Field(..., description="Operation status (success or failed)")
    error: str | None = Field(None, description="Error message if failed")


def main(params: dict) -> dict:
    """Discover available data in the network database.

    Args:
        params: {
            "pattern": "device"  # optional filter pattern
        }

    Returns:
        DiscoverDataOutput as dict with table information or error
    """
    # ========== STEP 1: Validate parameters with Pydantic ==========
    try:
        args = DiscoverDataInput(**params)
    except Exception as e:
        output = DiscoverDataOutput(
            tables=[],
            summary="",
            status="failed",
            error=f"Invalid parameters: {str(e)}"
        )
        return output.model_dump(exclude_none=True)

    # ========== STEP 2: List all tables ==========
    try:
        result = db_query(
            "SELECT DISTINCT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        )
        all_tables = [row["table_name"] for row in result]

        # ========== STEP 3: Apply pattern filter if provided ==========
        if args.pattern:
            tables = [t for t in all_tables if args.pattern.lower() in t.lower()]
        else:
            tables = all_tables

        # ========== STEP 4: Get row counts for each table ==========
        table_info = []
        for table in tables:
            try:
                count_result = db_query(f"SELECT COUNT(*) as cnt FROM {table}")
                count = count_result[0]["cnt"] if count_result else 0
                table_info.append(TableInfo(table=table, row_count=count))
            except Exception:
                # If we can't count, still include the table with -1
                table_info.append(TableInfo(table=table, row_count=-1))

        # ========== STEP 5: Build summary message ==========
        summary = f"Found {len(tables)} tables"
        if args.pattern:
            summary += f" matching '{args.pattern}'"
        summary += f" (total {len(all_tables)} tables in database)"

        output = DiscoverDataOutput(
            tables=table_info,
            summary=summary,
            status="success"
        )

    # ========== STEP 6: Handle errors ==========
    except Exception as e:
        output = DiscoverDataOutput(
            tables=[],
            summary="",
            status="failed",
            error=f"Failed to discover data: {str(e)}"
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
def discover_data(pattern: str | None = None) -> dict:
    """Discover available data in the network database.
    
    This tool explores and catalogs all available tables in the network database.
    It returns table names, row counts, and descriptions to help the LLM understand
    what data is available for querying.
    
    Args:
        pattern: Optional search pattern to filter tables (case-insensitive substring match)
    
    Returns:
        List of tables with row counts and summary information
    
    Examples:
        discover_data()  # Discover all tables
        discover_data(pattern="device")  # Find tables matching "device"
        discover_data(pattern="interface")  # Find tables matching "interface"
    """
    # Use Pydantic model for validation
    params = {"pattern": pattern}
    return main(params)


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return super().default(obj)


if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        input_data = json.loads(input_str) if input_str.strip() else {}
        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2, cls=DateTimeEncoder))
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

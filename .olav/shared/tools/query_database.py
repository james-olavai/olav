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


def main(params: dict) -> dict:
    """Query DuckDB database via data_gateway unified connection.

    Args:
        params: {
            "sql": "SELECT * FROM devices WHERE hostname='R1'"
        }

    Returns:
        {
            "data": [...],
            "count": 10,
            "status": "success"
        }
    """
    sql = params.get("sql")

    if not sql:
        return {"error": "Missing 'sql' parameter", "status": "failed"}

    try:
        # data_gateway.query_database returns list[dict] directly
        results = db_query(sql)

        return {
            "data": results,
            "count": len(results),
            "status": "success",
        }

    except Exception as e:
        error_msg = str(e)

        if (
            "does not exist" in error_msg
            or "no such table" in error_msg.lower()
            or "catalog error" in error_msg.lower()
        ):
            return {
                "error": error_msg,
                "error_type": "missing_view",
                "suggestion": "Use inspect_schema to check available tables and columns.",
                "status": "failed",
            }

        return {"error": error_msg, "error_type": "database_error", "status": "failed"}


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
        error_result = {"error": f"Invalid JSON input: {str(e)}", "status": "failed"}
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        error_result = {"error": f"Unexpected error: {str(e)}", "status": "failed"}
        # Print to stderr so SkillAdapter can see it
        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""
Query Database Script - Standard Template

This script queries the DuckDB database and returns results in JSON format.
It follows the standard template for all .olav/scripts/*.py files.

Usage:
    echo '{"sql": "SELECT * FROM v_interfaces LIMIT 5"}' | uv run python3 .olav/scripts/query_database.py
"""

import json
import sys
from pathlib import Path

# Add src to Python Path
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from olav.core.unified_database import UnifiedDatabase


def main(params: dict) -> dict:
    """Query DuckDB database

    Args:
        params: {
            "sql": "SELECT * FROM v_interfaces WHERE device='R1'"
        }

    Returns:
        {
            "results": [...],
            "count": 10,
            "timestamp": "2026-01-29 15:40:00"
        }
    """
    sql = params.get("sql")

    if not sql:
        return {"error": "Missing 'sql' parameter", "status": "failed"}

    try:
        udb = UnifiedDatabase()
        raw_results = udb.query(sql)

        # Convert tuples to dicts (UnifiedDatabase returns tuples)
        if raw_results:
            # Get column names from the connection
            conn = udb.conn
            columns = [desc[0] for desc in conn.description]
            results = [dict(zip(columns, row, strict=False)) for row in raw_results]
        else:
            results = []

        # Get data timestamp (try multiple sources)
        timestamp = None
        try:
            timestamp_query = """
                SELECT MAX(created_at) as latest_timestamp
                FROM raw_outputs
                LIMIT 1
            """
            timestamp_result = udb.query(timestamp_query)
            if timestamp_result and timestamp_result[0]:
                timestamp = timestamp_result[0][0]
        except Exception:
            # raw_outputs table doesn't exist, try alternatives
            try:
                timestamp_result = udb.query(
                    "SELECT MAX(snapshot_date) as latest_timestamp FROM v_system LIMIT 1"
                )
                if timestamp_result and timestamp_result[0]:
                    timestamp = timestamp_result[0][0]
            except Exception:
                pass  # Use current time as fallback

        return {
            "data": results,
            "count": len(results),
            "timestamp": str(timestamp) if timestamp else None,
            "status": "success",
        }

    except Exception as e:
        error_msg = str(e)

        # Check if error is about missing views/tables
        if (
            "does not exist" in error_msg
            or "no such table" in error_msg.lower()
            or "catalog error" in error_msg.lower()
        ):
            return {
                "error": error_msg,
                "error_type": "missing_view",
                "suggestion": "Database views not found. Use inspect_schema to check available views, or use smart_query for live CLI commands.",
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

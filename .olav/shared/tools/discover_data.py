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
    """Discover available data in the network database.

    Args:
        params: {
            "pattern": "device"  # optional filter pattern
        }

    Returns:
        {
            "tables": [...],
            "summary": "Found N tables...",
            "status": "success"
        }
    """
    pattern = params.get("pattern", "")

    try:
        # List all tables
        result = db_query(
            "SELECT DISTINCT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        )
        all_tables = [row["table_name"] for row in result]

        # Filter by pattern if provided
        if pattern:
            tables = [t for t in all_tables if pattern.lower() in t.lower()]
        else:
            tables = all_tables

        # Get row counts for each table
        table_info = []
        for table in tables:
            try:
                count_result = db_query(f"SELECT COUNT(*) as cnt FROM {table}")
                count = count_result[0]["cnt"] if count_result else 0
                table_info.append({"table": table, "row_count": count})
            except Exception:
                table_info.append({"table": table, "row_count": -1})

        summary = f"Found {len(tables)} tables"
        if pattern:
            summary += f" matching '{pattern}'"
        summary += f" (total {len(all_tables)} tables in database)"

        return {
            "tables": table_info,
            "summary": summary,
            "status": "success",
        }

    except Exception as e:
        return {"error": str(e), "status": "failed"}


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
    except Exception as e:
        print(json.dumps({"error": str(e), "status": "failed"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

"""List available APIs and their operations from the OLAV api_registry.

Tool: query_api_schema

Args (JSON):
    api_name:  str | None  — filter to one registered API (optional)
    tag:       str | None  — filter operations by tag (optional)
    db_path:   str | None  — override registry DB path (default: ~/.olav/olav_registry.duckdb)

Returns: JSON string
    {
      "apis": [{"api_name": "clab", "base_url": "...", "op_count": 42}],
      "operations": [{"api_name": "clab", "method": "GET", "path": "/api/v1/labs", ...}]
    }

If the registry DB does not exist or is empty, returns {"apis": [], "operations": []}.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow direct import of olav.core when run from skill context
_OLAV_SRC = Path(__file__).parents[5] / "src"
if str(_OLAV_SRC) not in sys.path:
    sys.path.insert(0, str(_OLAV_SRC))

import duckdb


def query_api_schema(args: dict) -> str:
    """Return registered APIs and optionally their operations."""
    api_name: str | None = args.get("api_name")
    tag: str | None = args.get("tag")
    db_path_str: str | None = args.get("db_path")

    if db_path_str:
        db_path = Path(db_path_str)
    else:
        try:
            from olav.core.api_registry import DEFAULT_DB
            db_path = DEFAULT_DB
        except ImportError:
            db_path = Path.home() / ".olav" / "olav_registry.duckdb"

    if not db_path.exists():
        return json.dumps({"apis": [], "operations": []})

    try:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            # List all APIs with op_count
            api_rows = con.execute(
                """
                SELECT s.api_name, s.base_url, s.fetched_at,
                       COUNT(o.path) AS op_count
                FROM api_registry.schemas s
                LEFT JOIN api_registry.operations o USING (api_name)
                GROUP BY s.api_name, s.base_url, s.fetched_at
                ORDER BY s.api_name
                """
            ).fetchall()

            apis = [
                {"api_name": r[0], "base_url": r[1], "fetched_at": r[2], "op_count": r[3]}
                for r in api_rows
            ]

            # Filter apis list if api_name provided
            if api_name:
                apis = [a for a in apis if a["api_name"] == api_name]

            # Fetch operations if api_name or tag filter is given
            operations: list[dict] = []
            if api_name or tag:
                where_clauses = []
                params: list = []
                if api_name:
                    where_clauses.append("api_name = ?")
                    params.append(api_name)
                if tag:
                    where_clauses.append("list_contains(tags, ?)")
                    params.append(tag)

                where_sql = " AND ".join(where_clauses)
                op_rows = con.execute(
                    f"""
                    SELECT api_name, method, path, summary, tags
                    FROM api_registry.operations
                    WHERE {where_sql}
                    ORDER BY method, path
                    """,
                    params,
                ).fetchall()

                operations = [
                    {
                        "api_name": r[0],
                        "method": r[1],
                        "path": r[2],
                        "summary": r[3],
                        "tags": r[4] or [],
                    }
                    for r in op_rows
                ]
        finally:
            con.close()

        return json.dumps({"apis": apis, "operations": operations})

    except Exception as exc:
        return json.dumps({"error": str(exc), "apis": [], "operations": []})


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Query OLAV API registry")
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    print(query_api_schema(json.loads(parsed.args_json)))

"""Get field names for an API definition (request/response schema).

Tool: get_definition_schema

Args (JSON):
    api_name:  str        — registered API name (e.g. "clab")
    def_name:  str        — definition name (e.g. "TopologyRequest", "Lab")
    db_path:   str | None — override registry DB path (optional)

Returns: JSON string
    {"fields": ["name", "topology", ...]}        ← known definition
    {"fields": []}                                ← unknown definition (no error raised)
    {"error": "...", "fields": []}               ← DB error
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_OLAV_SRC = Path(__file__).parents[5] / "src"
if str(_OLAV_SRC) not in sys.path:
    sys.path.insert(0, str(_OLAV_SRC))

import duckdb


def get_definition_schema(args: dict) -> str:
    """Return field names for a registered API definition."""
    api_name: str = args["api_name"]
    def_name: str = args["def_name"]
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
        return json.dumps({"fields": []})

    try:
        con = duckdb.connect(str(db_path), read_only=True)
        row = con.execute(
            "SELECT fields FROM api_registry.definitions WHERE api_name = ? AND def_name = ?",
            [api_name, def_name],
        ).fetchone()
        con.close()

        if not row:
            return json.dumps({"fields": []})

        fields_obj = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        field_names = list(fields_obj.keys()) if isinstance(fields_obj, dict) else []
        return json.dumps({"fields": field_names})

    except Exception as exc:
        return json.dumps({"error": str(exc), "fields": []})


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Get API definition schema fields")
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    print(get_definition_schema(json.loads(parsed.args_json)))

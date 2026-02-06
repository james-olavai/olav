import json
import sys
from pathlib import Path

# Add src to Python Path
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from olav.lib.data_gateway import query_database as db_query


def main(params: dict) -> dict:
    """Introspection for SQL Agent - uses data_gateway unified connection."""
    table_name = params.get("table_name")

    if table_name:
        # Get columns for a specific table
        try:
            result = db_query(f"DESCRIBE {table_name}")
            columns = [row.get("column_name", row.get("Field", "")) for row in result]
            return {"status": "success", "table": table_name, "columns": columns}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    else:
        # List all tables (from unified connection's main schema)
        try:
            result = db_query(
                "SELECT DISTINCT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            )
            tables = [row["table_name"] for row in result]
            return {"status": "success", "tables": tables}
        except Exception as e:
            return {"status": "error", "message": str(e)}


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
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}), file=sys.stderr)
        sys.exit(1)

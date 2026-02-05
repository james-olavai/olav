import json
import sys
from pathlib import Path

# Add src to Python Path
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from olav.core.unified_database import UnifiedDatabase


def main(params: dict) -> dict:
    """Introspection for SQL Agent"""
    table_name = params.get("table_name")
    udb = UnifiedDatabase()

    if table_name:
        # Get columns for a specific table
        try:
            res = udb.conn.execute(f"DESCRIBE {table_name}").fetchall()
            columns = [row[0] for row in res]
            return {"status": "success", "table": table_name, "columns": columns}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    else:
        # List all views
        try:
            res = udb.conn.execute(
                "SELECT table_name FROM information_schema.views WHERE table_schema = 'main'"
            ).fetchall()
            views = [row[0] for row in res]
            return {"status": "success", "views": views}
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

import sys
import json
from pathlib import Path

# Add src to Python Path
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from olav.core.unified_database import UnifiedDatabase

def main(params: dict) -> dict:
    """Check SQL cache"""
    query = params.get("query")
    if not query:
        return {"status": "error", "message": "No query provided"}
    
    udb = UnifiedDatabase()
    try:
        result = udb.conn.execute(
            "SELECT sql_query FROM commands.nl_sql_cache WHERE user_query = ?",
            [query.strip().lower()]
        ).fetchone()
        
        if result:
            return {"status": "success", "found": True, "sql": result[0]}
        else:
            return {"status": "success", "found": False}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        if not input_str:
            input_data = {}
        else:
            input_data = json.loads(input_str)
            
        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}), file=sys.stderr)
        sys.exit(1)

import sys
import json
from olav.core.unified_database import UnifiedDatabase

def main(params: dict) -> dict:
    """Get health status for a specific device."""
    device = params.get("device_name") or params.get("arg")
    if not device:
        return {"error": "Missing 'device_name' parameter"}
    
    with UnifiedDatabase() as db:
        result = db.get_device_health(device)
    
    if "error" in result:
        return {"status": "error", "message": result["error"]}
    
    return {"status": "success", "data": result}

if __name__ == "__main__":
    try:
        input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
        print(json.dumps(main(input_data)))
    except Exception as e:
        print(json.dumps({"error": str(e)}))

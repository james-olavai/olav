import json
import sys

from olav.core.unified_database import UnifiedDatabase


def main(params: dict) -> dict:
    """Find IP location in the network."""
    ip = params.get("ip_address") or params.get("arg")
    if not ip:
        return {"error": "Missing 'ip_address' parameter"}

    with UnifiedDatabase() as db:
        result = db.find_ip_location(ip)

    if not result:
        return {"status": "not_found", "message": f"IP {ip} not found in ARP table"}

    return {"status": "success", "data": result}


if __name__ == "__main__":
    try:
        input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
        print(json.dumps(main(input_data)))
    except Exception as e:
        print(json.dumps({"error": str(e)}))

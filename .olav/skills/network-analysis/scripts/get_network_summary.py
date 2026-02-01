import json

from olav.core.unified_database import UnifiedDatabase


def main(params: dict = None) -> dict:
    """Get network-wide summary statistics."""
    with UnifiedDatabase() as db:
        result = db.get_network_summary()

    return {"status": "success", "data": result}


if __name__ == "__main__":
    try:
        # For network summary, input data is usually empty but we keep the boilerplate
        # Avoid sys.stdin.read() if it's empty to prevent hanging
        print(json.dumps(main()))
    except Exception as e:
        print(json.dumps({"error": str(e)}))

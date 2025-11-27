"""Quick test script to check BGP data fields."""
import sys
from pathlib import Path

# Add project root to sys.path
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

import asyncio
from olav.tools.suzieq_parquet_tool import suzieq_query
from olav.workflows.deep_dive import DeepDiveWorkflow


async def test():
    result = await suzieq_query.ainvoke({"table": "bgp", "method": "get", "max_age_hours": 0})
    print(f"Count: {result.get('count')}")
    print(f"Columns: {len(result.get('columns', []))}")
    print("\nBGP Sessions:")
    for r in result.get("data", [])[:8]:
        hostname = r.get("hostname", "?")
        peer = r.get("peer", "?")
        state = r.get("state", "?")
        reason = r.get("reason", "")
        notificn = r.get("notificnReason", "")
        print(f"  {hostname} -> {peer}: state={state}, reason={reason}, notificn={notificn}")

    # Test new _extract_diagnostic_fields method
    print("\n\n--- Testing _extract_diagnostic_fields ---")
    workflow = DeepDiveWorkflow()
    data = result.get("data", [])
    extracted = workflow._extract_diagnostic_fields(data, "bgp")
    print(extracted)


if __name__ == "__main__":
    asyncio.run(test())

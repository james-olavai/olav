"""Store Network Event Memory Tool.

Stores a high-level network episode summary in LanceDB long-term memory.

Design reference: dev_docs/archive/LANCEDB_MEMORY_SYSTEM_INTEGRATION.md
  Section 2/OCM Core: "Network Event Memory — storing summarized network
  anomalies and episodes (NOT raw system logs) for root-cause analysis."

Only high-level summaries should be stored here, e.g.:
  - "Datacenter-A experienced BGP flaps from 10:00 to 10:15"
  - "OSPF adjacency dropped between R1 and R2 due to MTU mismatch"
  - "Interface Gi0/1 on Core-SW bounced 3 times on 2026-03-01"

Raw CLI output, system logs, and full config dumps MUST NOT be stored here.
"""

import logging
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

from langchain_core.tools import tool

from olav.core.memory import MEMORY_TABLE, get_store, store_network_event

logger = logging.getLogger(__name__)


@tool
def record_network_event(
    summary: str,
    device: str | None = None,
    event_type: str | None = None,
    scope: str = "global",
) -> str:
    """Store a summarized network event in long-term memory for future recall.

    Use this AFTER diagnosing a network issue or observing a network state change
    to persist the knowledge for future correlation and root-cause analysis.

    Only store high-level summaries — NOT raw CLI output, full configs, or
    system logs. The goal is to build an experience database the agent can
    reference in future troubleshooting sessions.

    Args:
        summary:    Human-readable episode description (max 200 chars recommended).
                    Examples:
                      - "BGP session between R1 and R2 flapped 3 times due to hold-timer expiry"
                      - "OSPF neighbor loss on Gi0/0 caused by MTU mismatch (R3=1500, R4=1472)"
                      - "VLAN 100 missing on Core-SW-01 triggered L2 black-hole for 15 minutes"
        device:     Primary device involved (optional, e.g. "R1", "Core-SW-01").
        event_type: Short category label (optional).
                    Common values: "bgp-flap", "ospf-drop", "interface-bounce",
                    "vlan-missing", "route-leak", "cpu-spike", "link-down".
        scope:      Memory namespace for isolation. Use the agent name (e.g. "ops",
                    "config") or "global" for cross-agent visibility.

    Returns:
        Confirmation message with the assigned memory ID.
    """
    if not summary or not summary.strip():
        return "Error: summary must not be empty."

    try:
        store = get_store()
        if not store.table_exists(MEMORY_TABLE):
            store.create_table(MEMORY_TABLE)

        result = store_network_event(
            store=store,
            summary=summary.strip(),
            device=device,
            event_type=event_type,
            scope=scope,
        )

        if result.get("status") == "success":
            return (
                f"✓ Network event stored in long-term memory (id={result['id']}).\n"
                f"  Summary: {summary[:100]}{'...' if len(summary) > 100 else ''}\n"
                f"  Device: {device or 'N/A'} | Type: {event_type or 'N/A'} | Scope: {scope}"
            )
        else:
            return f"Failed to store network event: {result.get('message', 'unknown error')}"

    except Exception as e:
        logger.error(f"record_network_event failed: {e}")
        return f"Error storing network event: {e}"


if __name__ == "__main__":
    import json
    data = json.loads(sys.stdin.read())
    print(json.dumps(record_network_event.invoke(data), ensure_ascii=False))

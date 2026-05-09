"""inspect_devices @tool — facts lookup for named devices.

R-AGENT-HIERARCHY post-Phase-D inspector pattern (2026-05-09):
small models can't reliably compose multi-line Python in
``run_python_simulation``.  Replace the sandbox with narrow,
typed inspector tools that wrap ``model.facts`` / ``model.graph``.

Each inspector:
* takes typed args (Pydantic schema enforced at LLM decode time)
* returns a dict the LLM can read directly
* contains zero LLM-authored code
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

# Eager import to avoid asyncio.gather _ModuleLock deadlocks when
# LangGraph runs multiple inspect_* tools in parallel.
from olav_netops.sim import load_network_model


_FACT_FIELDS = ("platform", "loopback", "local_as", "mgmt_ip", "role")


@tool
def inspect_devices(devices: list[str]) -> dict[str, Any]:
    """
    Get consolidated facts for the named devices.

    Returns the facts that *could be resolved* per device, the list
    of facts that *could not* be resolved (so the LLM doesn't read
    None as "configured to nothing"), and a list of devices that are
    not in the inventory at all.

    Use this BEFORE any change plan to see what platform / AS /
    loopback each device has.

    Args:
        devices: List of hostnames to look up.  E.g. ``["R1", "R3"]``.

    Returns:
        ``{
            "found": {hostname: {field: value, ...}},   # only resolved fields
            "unknown_facts": {hostname: [field, ...]},  # fields that were None
            "unknown_devices": [hostname, ...],         # not in inventory
        }``.

    Example:
        >>> inspect_devices(["R2", "R3", "R1", "Rfoo"])
        {
            "found": {
                "R2": {"platform": "cisco_ios", "local_as": 65001,
                       "loopback": "2.2.2.2", "mgmt_ip": "192.168.100.102",
                       "role": "border"},
                "R3": {"platform": "cisco_ios", "local_as": 65000,
                       "loopback": "3.3.3.3", "mgmt_ip": "192.168.100.103",
                       "role": "core"},
                "R1": {"platform": "juniper_junos",
                       "mgmt_ip": "192.168.100.101", "role": "border"},
            },
            "unknown_facts": {
                "R1": ["loopback", "local_as"]   # parser didn't capture
            },
            "unknown_devices": ["Rfoo"],
        }
    """
    model = load_network_model()
    facts = model.facts

    found: dict[str, dict[str, Any]] = {}
    unknown_facts: dict[str, list[str]] = {}
    unknown_devices: list[str] = []

    for d in devices:
        record = facts.get(d)
        if record is None:
            unknown_devices.append(d)
            continue
        resolved = {k: v for k, v in record.items() if v is not None}
        missing = [
            f for f in _FACT_FIELDS
            if record.get(f) is None
        ]
        found[d] = resolved
        if missing:
            unknown_facts[d] = missing

    return {
        "found": found,
        "unknown_facts": unknown_facts,
        "unknown_devices": unknown_devices,
    }

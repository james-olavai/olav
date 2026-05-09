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


@tool
def inspect_devices(devices: list[str]) -> dict[str, Any]:
    """
    Get consolidated facts for the named devices.

    Returns a dict ``{hostname: {platform, loopback, local_as, mgmt_ip, role}}``.
    Devices not in the inventory are silently dropped from the result.
    Use this BEFORE any change plan to see what platform / AS / loopback
    each device has.

    Args:
        devices: List of hostnames to look up.  E.g. ``["R1", "R3"]``.

    Returns:
        ``{hostname: facts_dict}`` for every device found in
        ``netops.devices`` whose facts could be resolved.

    Example:
        >>> inspect_devices(["R2", "R3"])
        {
            "R2": {"platform": "cisco_ios", "local_as": 65001,
                   "loopback": "2.2.2.2", "mgmt_ip": "192.168.100.102",
                   "role": "border"},
            "R3": {"platform": "cisco_ios", "local_as": 65000,
                   "loopback": "3.3.3.3", "mgmt_ip": "192.168.100.103",
                   "role": "core"},
        }
    """
    model = load_network_model()
    return {d: model.facts.get(d) for d in devices if d in model.facts}

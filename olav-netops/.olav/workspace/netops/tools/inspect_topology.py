"""inspect_topology @tool — L2 adjacencies for given devices."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

# Eager import to avoid asyncio.gather _ModuleLock deadlocks when
# LangGraph runs multiple inspect_* tools in parallel.
from olav_netops.sim import load_network_model


@tool
def inspect_topology(devices: list[str], depth: int = 1) -> dict[str, Any]:
    """
    Show L2 physical adjacencies (LLDP / CDP) for the named devices.

    Each device's neighbors come with the source/destination interface
    pair, the discovery protocol, and the link status.  Use this to
    answer "what is X connected to" or "is there a direct link
    between X and Y" before designing a change.

    **Validation**: devices not in the topology graph are returned in
    ``unknown_devices`` rather than silently dropped.  An empty
    neighbor list means "no neighbors found" — distinct from "device
    not in graph at all".

    Args:
        devices: List of hostnames.
        depth: How many hops outward to expand.  ``1`` (default) returns
            only direct neighbors; ``2`` adds neighbors-of-neighbors.

    Returns:
        ``{
            "neighbors": {hostname: [{from, neighbor, hop, local_intf,
                                      remote_intf, protocol,
                                      link_status}, ...]},
            "unknown_devices": [hostname, ...],
        }``.

    Example:
        >>> inspect_topology(["R2", "Rfoo"])
        {
          "neighbors": {
            "R2": [
              {"from": "R2", "neighbor": "R4", "hop": 1,
               "local_intf": "GigabitEthernet2",
               "remote_intf": "Ethernet0/0",
               "protocol": "CDP", "link_status": "up"},
            ]
          },
          "unknown_devices": ["Rfoo"]
        }
    """
    model = load_network_model()
    g = model.graph

    if depth < 1:
        depth = 1
    if depth > 3:
        depth = 3  # cap to keep return size sane for small models

    neighbors: dict[str, list[dict[str, Any]]] = {}
    unknown_devices: list[str] = []
    for device in devices:
        if device not in g.nodes:
            unknown_devices.append(device)
            continue
        # BFS up to `depth` hops
        seen: set[str] = {device}
        frontier: list[str] = [device]
        device_neighbors: list[dict[str, Any]] = []
        for hop in range(depth):
            next_frontier: list[str] = []
            for src in frontier:
                for dst in g.successors(src):
                    if dst in seen:
                        continue
                    seen.add(dst)
                    next_frontier.append(dst)
                    edge = g[src][dst]
                    device_neighbors.append({
                        "from": src,
                        "neighbor": dst,
                        "hop": hop + 1,
                        "local_intf": edge.get("source_interface"),
                        "remote_intf": edge.get("destination_interface"),
                        "protocol": edge.get("protocol"),
                        "link_status": edge.get("link_status"),
                    })
            frontier = next_frontier
        neighbors[device] = device_neighbors

    return {
        "neighbors": neighbors,
        "unknown_devices": unknown_devices,
    }

"""inspect_routing @tool — BGP / OSPF adjacency state for devices."""
from __future__ import annotations

from typing import Any, Literal

from langchain_core.tools import tool

# Eager import to avoid asyncio.gather _ModuleLock deadlocks when
# LangGraph runs multiple inspect_* tools in parallel.
from olav_netops.sim import load_network_model


@tool
def inspect_routing(
    devices: list[str],
    protocol: Literal["bgp", "ospf", "both"] = "both",
) -> dict[str, Any]:
    """
    Show BGP / OSPF neighbor state per device.

    Reads the L3 overlays already attached to ``model.graph`` —
    no SQL, no NetworkX code needed from your side.  Use this to
    answer "is BGP up between X and Y" or "what AS is R3 in"
    before designing a change.

    Args:
        devices: List of hostnames to inspect.
        protocol: ``"bgp"`` for BGP sessions only, ``"ospf"`` for OSPF
            adjacencies only, ``"both"`` (default) for combined output.

    Returns:
        ``{hostname: {bgp: [...], ospf: [...]}}`` where each list
        item is ``{neighbor, neighbor_as, state}`` (BGP) or
        ``{neighbor, state}`` (OSPF).

    Example:
        >>> inspect_routing(["R2", "R3"], "bgp")
        {
          "R2": {"bgp": [{"neighbor": "R4", "neighbor_as": 65001,
                          "state": "Established"}], "ospf": []},
          "R3": {"bgp": [{"neighbor": "SW1", "neighbor_as": 65000,
                          "state": "Established"}], "ospf": []},
        }
    """
    model = load_network_model()
    g = model.graph

    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for device in devices:
        if device not in g.nodes:
            continue
        bgp_list: list[dict[str, Any]] = []
        ospf_list: list[dict[str, Any]] = []
        for neighbor in g.successors(device):
            edge = g[device][neighbor]
            if protocol in ("bgp", "both") and edge.get("bgp_session"):
                bgp_list.append({
                    "neighbor": neighbor,
                    "neighbor_as": edge.get("bgp_neighbor_as"),
                    "state": edge.get("bgp_session_state"),
                })
            if protocol in ("ospf", "both") and edge.get("ospf_state"):
                ospf_list.append({
                    "neighbor": neighbor,
                    "state": edge.get("ospf_state"),
                })
        result[device] = {"bgp": bgp_list, "ospf": ospf_list}
    return result

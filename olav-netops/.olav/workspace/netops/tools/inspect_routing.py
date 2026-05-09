"""inspect_routing @tool — BGP / OSPF adjacency state for devices."""
from __future__ import annotations

from typing import Any, Literal

import duckdb
from langchain_core.tools import tool

# Eager import to avoid asyncio.gather _ModuleLock deadlocks when
# LangGraph runs multiple inspect_* tools in parallel.
from olav.core.config import MAIN_DB_PATH
from olav_netops.sim import load_network_model


@tool
def inspect_routing(
    devices: list[str],
    protocol: Literal["bgp", "ospf", "both"] = "both",
) -> dict[str, Any]:
    """
    Show BGP / OSPF neighbor state per device.

    Reads the L3 overlays attached to ``model.graph`` AND falls back
    to the raw ``v_show_ip_bgp_summary_auto`` view for any BGP
    neighbor whose IP could not be resolved to a known hostname.
    Use this to answer "is BGP up between X and Y" or "what AS is R3
    in" before designing a change.

    Args:
        devices: List of hostnames to inspect.
        protocol: ``"bgp"`` for BGP sessions only, ``"ospf"`` for OSPF
            adjacencies only, ``"both"`` (default) for combined output.

    Returns:
        ``{hostname: {
            bgp: [{neighbor, neighbor_as, state}, ...],
            unresolved_bgp: [{neighbor_ip, neighbor_as, state,
                              prefixes_received}, ...],
            ospf: [{neighbor, state}, ...]
        }}``.

        ``bgp`` lists sessions where the neighbor IP was resolved to
        a known hostname.  ``unresolved_bgp`` lists sessions whose
        neighbor IP did not match any device's loopback in the
        topology — the BGP session is real (raw view confirms) but
        the topology graph could not surface it.  Treat unresolved
        entries as evidence of either a peer outside the inventory
        OR a missing-loopback fact in the inventory.

        ``state`` is normalised: "Established" when the underlying
        Cisco field is numeric (and ``prefixes_received`` carries the
        count); otherwise the literal state name (Idle / Active / etc).

    Example:
        >>> inspect_routing(["R3"], "bgp")
        {
          "R3": {
            "bgp": [],
            "unresolved_bgp": [{"neighbor_ip": "1.1.1.1",
                                "neighbor_as": 65000,
                                "state": "Established",
                                "prefixes_received": 0}],
            "ospf": []
          }
        }
    """
    model = load_network_model()
    g = model.graph

    # Step 1: graph-resolved sessions (same as before)
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    resolved_ips_by_device: dict[str, set[str]] = {}
    for device in devices:
        if device not in g.nodes:
            continue
        bgp_list: list[dict[str, Any]] = []
        ospf_list: list[dict[str, Any]] = []
        resolved_ips: set[str] = set()
        for neighbor in g.successors(device):
            edge = g[device][neighbor]
            if protocol in ("bgp", "both") and edge.get("bgp_session"):
                bgp_list.append({
                    "neighbor": neighbor,
                    "neighbor_as": edge.get("bgp_neighbor_as"),
                    "state": edge.get("bgp_session_state"),
                })
                # Track the peer IP recorded on the edge to dedupe
                # against the raw BGP view fallback below.
                peer_ip = edge.get("bgp_neighbor_ip")
                if peer_ip:
                    resolved_ips.add(str(peer_ip))
            if protocol in ("ospf", "both") and edge.get("ospf_state"):
                ospf_list.append({
                    "neighbor": neighbor,
                    "state": edge.get("ospf_state"),
                })
        result[device] = {
            "bgp": bgp_list,
            "unresolved_bgp": [],
            "ospf": ospf_list,
        }
        resolved_ips_by_device[device] = resolved_ips

    # Step 2: raw BGP fallback — surface neighbors the graph couldn't
    # resolve.  Reads ``v_bgp_neighbors_auto`` which UNIONs Cisco
    # (``show ip bgp summary``) + Junos (``show bgp summary``) sources
    # with already-decoded ``state`` + ``prefixes_received`` columns.
    if protocol in ("bgp", "both") and result:
        try:
            with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
                placeholders = ",".join(["?"] * len(result))
                rows = conn.execute(
                    f"""
                    SELECT device_name, neighbor_ip, neighbor_as,
                           state, prefixes_received
                    FROM netops.v_bgp_neighbors_auto
                    WHERE device_name IN ({placeholders})
                      AND neighbor_ip IS NOT NULL
                    """,
                    list(result.keys()),
                ).fetchall()
        except Exception:
            rows = []
        for device, peer_ip, peer_as, state, prefixes_received in rows:
            if device not in result:
                continue
            if str(peer_ip) in resolved_ips_by_device.get(device, set()):
                continue  # already covered by the graph overlay
            result[device]["unresolved_bgp"].append({
                "neighbor_ip": str(peer_ip),
                "neighbor_as": int(peer_as) if peer_as is not None else None,
                "state": state or "Unknown",
                "prefixes_received": (
                    int(prefixes_received)
                    if prefixes_received is not None else None
                ),
            })

    return result

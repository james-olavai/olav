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
            bgp: [{neighbor, neighbor_ip, neighbor_as, state,
                   prefixes_received, resolved}, ...],
            ospf: [{neighbor, state}, ...]
        }}``.

        ``bgp`` is one merged list — every session whether or not the
        neighbor IP could be mapped to a known hostname.  Each row has:

        * ``neighbor`` — hostname (resolved) or ``null``
        * ``neighbor_ip`` — peer IP (always present)
        * ``neighbor_as`` — peer AS
        * ``state`` — "Established" / "Idle" / "Active" / etc.  Numeric
          Cisco state field is decoded to "Established" automatically.
        * ``prefixes_received`` — INTEGER, only set when state =
          Established and the source carries a count
        * ``resolved`` — bool: ``true`` if the IP mapped to a hostname
          via the topology graph, ``false`` if only raw view data
          (peer outside inventory OR missing-loopback fact)

        Treat ``resolved=false`` as evidence of inventory gap, not
        as "no BGP".  An "empty bgp list" only means ``len(bgp)==0``.

    Example:
        >>> inspect_routing(["R3"], "bgp")
        {
          "R3": {
            "bgp": [{"neighbor": null, "neighbor_ip": "1.1.1.1",
                     "neighbor_as": 65000, "state": "Established",
                     "prefixes_received": 0, "resolved": false}],
            "ospf": []
          }
        }
    """
    model = load_network_model()
    g = model.graph

    # Discovery mode — empty list = enumerate every device in the graph.
    target_devices: list[str] = list(devices) if devices else sorted(g.nodes)

    # Step 1: graph-resolved sessions
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    resolved_ips_by_device: dict[str, set[str]] = {}
    for device in target_devices:
        if device not in g.nodes:
            continue
        bgp_list: list[dict[str, Any]] = []
        ospf_list: list[dict[str, Any]] = []
        resolved_ips: set[str] = set()
        for neighbor in g.successors(device):
            edge = g[device][neighbor]
            if protocol in ("bgp", "both") and edge.get("bgp_session"):
                peer_ip = edge.get("bgp_neighbor_ip")
                bgp_list.append({
                    "neighbor": neighbor,
                    "neighbor_ip": str(peer_ip) if peer_ip else None,
                    "neighbor_as": edge.get("bgp_neighbor_as"),
                    "state": edge.get("bgp_session_state"),
                    "prefixes_received": edge.get("bgp_prefixes_received"),
                    "resolved": True,
                })
                if peer_ip:
                    resolved_ips.add(str(peer_ip))
            if protocol in ("ospf", "both") and edge.get("ospf_state"):
                ospf_list.append({
                    "neighbor": neighbor,
                    "state": edge.get("ospf_state"),
                })
        result[device] = {
            "bgp": bgp_list,
            "ospf": ospf_list,
        }
        resolved_ips_by_device[device] = resolved_ips

    # Build the set of "every loopback known to facts" so we can
    # dedupe raw rows whose neighbor_ip points at a hostname already
    # surfaced as a resolved session.
    known_loopback_ips = {
        str(f.get("loopback"))
        for f in model.facts.values()
        if f.get("loopback")
    }

    # Step 2: append unresolved (raw-only) sessions — same merged list
    # as resolved ones, just resolved=false.  v_bgp_neighbors_auto
    # already UNIONs Cisco + Junos with decoded state + prefixes.
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
            if str(peer_ip) in known_loopback_ips:
                # The IP IS a known device loopback — fact-level
                # resolution exists even though the graph overlay
                # didn't carry the IP.  Find the matching resolved
                # row and merge the raw view's richer fields
                # (prefixes_received, decoded state) into it instead
                # of emitting a duplicate.
                target_hostname = next(
                    (h for h, f in model.facts.items()
                     if str(f.get("loopback")) == str(peer_ip)),
                    None,
                )
                if target_hostname is not None:
                    for row in result[device]["bgp"]:
                        if row.get("neighbor") == target_hostname:
                            if row.get("neighbor_ip") is None:
                                row["neighbor_ip"] = str(peer_ip)
                            if (row.get("prefixes_received") is None
                                    and prefixes_received is not None):
                                row["prefixes_received"] = int(prefixes_received)
                            if state and (
                                row.get("state") in (None, "Unknown")
                            ):
                                row["state"] = state
                            break
                continue
            result[device]["bgp"].append({
                "neighbor": None,
                "neighbor_ip": str(peer_ip),
                "neighbor_as": int(peer_as) if peer_as is not None else None,
                "state": state or "Unknown",
                "prefixes_received": (
                    int(prefixes_received)
                    if prefixes_received is not None else None
                ),
                "resolved": False,
            })

    return result

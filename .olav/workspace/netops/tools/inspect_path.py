"""inspect_path @tool — end-to-end path between two devices, with
ECMP detection.

R-VERTICAL-SLICE follow-on P2 (2026-05-10, dev_docs/74).  Exposes
NetworkX shortest_path + all_simple_paths via a typed inspector.
Closes a real capability gap: previously the agent could answer
"what's R3 connected to" (inspect_topology, 1-hop) and "what
breaks if R3 fails" (inspect_blast_radius, components-only) but
NOT "what path does traffic take from R1 to R5".
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

# Eager import — same _ModuleLock concern as the rest of the inspect_*
# family.
from olav_netops.sim import load_network_model


@tool
def inspect_path(
    src: str,
    dst: str,
    max_paths: int = 3,
) -> dict[str, Any]:
    """
    Find the L2 path(s) between two devices and report ECMP shape.

    Uses NetworkX over the unified L2 + L3 overlay graph
    (``model.graph``).  Reports the shortest path AND any equal-
    cost alternates up to ``max_paths``.

    Use this when the user asks "how does traffic from X reach Y",
    "is there a loop-free path", or "do we have ECMP between A and B".

    Args:
        src: Source hostname (must be in topology).
        dst: Destination hostname (must be in topology).
        max_paths: Cap on number of alternate paths returned
            (default 3, max 10).  Equal-cost paths are detected by
            same hop-count as the shortest path.

    Returns:
        On success::

            {
              "status": "success",
              "src": "R1",
              "dst": "R3",
              "shortest_path": ["R1", "SW1", "R3"],
              "shortest_hops": 2,
              "all_paths": [
                {"path": [...], "hops": N, "equal_cost": bool}, ...
              ],
              "ecmp": {
                "is_ecmp": false,
                "ecmp_count": 1,         # >1 means ECMP exists
              }
            }

        On error::

            {"status": "error", "error_kind": "device_not_in_graph",
             "message": "...", "available_devices": [...]}
            {"status": "error", "error_kind": "no_path",
             "message": "no path from src to dst — they're in
                         different components"}

    Example:
        >>> inspect_path("R1", "R3")
        {"shortest_path": ["R1", "R3"], "shortest_hops": 1,
         "all_paths": [{"path": ["R1", "R3"], "hops": 1,
                        "equal_cost": true}],
         "ecmp": {"is_ecmp": false, "ecmp_count": 1}}
    """
    import networkx as nx
    model = load_network_model()
    g = model.graph

    if src not in g.nodes:
        return {
            "status": "error",
            "error_kind": "device_not_in_graph",
            "message": (f"src device {src!r} not in topology graph"),
            "available_devices": sorted(g.nodes),
        }
    if dst not in g.nodes:
        return {
            "status": "error",
            "error_kind": "device_not_in_graph",
            "message": (f"dst device {dst!r} not in topology graph"),
            "available_devices": sorted(g.nodes),
        }

    if src == dst:
        return {
            "status": "success",
            "src": src,
            "dst": dst,
            "shortest_path": [src],
            "shortest_hops": 0,
            "all_paths": [{"path": [src], "hops": 0, "equal_cost": True}],
            "ecmp": {"is_ecmp": False, "ecmp_count": 1},
        }

    # NetworkX needs an undirected view to find both-direction paths
    # (graph is DiGraph; topology links are bidirectional in reality).
    undirected = g.to_undirected(as_view=True)

    try:
        shortest = nx.shortest_path(undirected, src, dst)
    except nx.NetworkXNoPath:
        return {
            "status": "error",
            "error_kind": "no_path",
            "message": (
                f"No path from {src} to {dst} — they're in different "
                f"connected components."
            ),
            "src": src,
            "dst": dst,
        }

    shortest_hops = len(shortest) - 1
    max_paths = max(1, min(max_paths, 10))

    # all_simple_paths up to shortest+2 hops to find ECMP candidates
    # without exhaustively enumerating long paths.
    all_paths_list: list[dict[str, Any]] = []
    for i, p in enumerate(nx.all_simple_paths(
        undirected, src, dst, cutoff=shortest_hops + 2
    )):
        if len(all_paths_list) >= max_paths:
            break
        hops = len(p) - 1
        all_paths_list.append({
            "path": p,
            "hops": hops,
            "equal_cost": hops == shortest_hops,
        })

    ecmp_count = sum(1 for ap in all_paths_list if ap["equal_cost"])

    return {
        "status": "success",
        "src": src,
        "dst": dst,
        "shortest_path": shortest,
        "shortest_hops": shortest_hops,
        "all_paths": all_paths_list,
        "ecmp": {
            "is_ecmp": ecmp_count > 1,
            "ecmp_count": ecmp_count,
        },
    }

"""inspect_critical_nodes @tool — single-points-of-failure +
centrality analysis on the topology graph.

R-VERTICAL-SLICE follow-on P3 (2026-05-10, dev_docs/74).  Exposes
NetworkX articulation_points + betweenness_centrality so the agent
can answer "which devices are most critical to overall connectivity"
without the user enumerating every device-loss what-if manually.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from olav_netops.sim import load_network_model


@tool
def inspect_critical_nodes(top_n: int = 5) -> dict[str, Any]:
    """
    Identify topology bottlenecks via two measures.

    1. **Articulation points** (also called "cut vertices") — devices
       whose failure would partition the network into >1 component.
       Hard "single points of failure".  Computed via
       ``nx.articulation_points`` on the undirected graph.

    2. **Betweenness centrality** — devices that lie on the most
       shortest paths between other device pairs.  Soft "important
       transit" measure.  A node with high betweenness but no SPOF
       status is still a hot-spot candidate for capacity planning.

    Use this BEFORE proposing failure-tolerance changes ("which
    device should we add a redundant link to") or for capacity-
    planning questions ("which nodes carry the most transit").

    Args:
        top_n: Cap on number of nodes returned per measure
            (default 5, max 20).

    Returns:
        ``{
          "status": "success",
          "node_count": N,
          "articulation_points": [
            {"device": "R1", "would_isolate": ["SW1", ...]}, ...
          ],
          "betweenness_top": [
            {"device": "R3", "score": 0.42}, ...
          ],
        }``.

    Example:
        >>> inspect_critical_nodes(top_n=3)
        {"articulation_points": [
            {"device": "R3", "would_isolate": ["SW1"]}],
         "betweenness_top": [
            {"device": "R3", "score": 0.45},
            {"device": "R1", "score": 0.28}, ...]}
    """
    import networkx as nx
    model = load_network_model()
    g = model.graph
    undirected = g.to_undirected(as_view=True)
    n_nodes = undirected.number_of_nodes()

    if n_nodes < 3:
        return {
            "status": "error",
            "error_kind": "graph_too_small",
            "message": (
                f"Graph has {n_nodes} nodes — need at least 3 for "
                "meaningful articulation / centrality."
            ),
        }

    top_n = max(1, min(top_n, 20))

    # Articulation points + which nodes they isolate
    articulation_list: list[dict[str, Any]] = []
    try:
        pre_components = nx.number_connected_components(undirected)
        for ap in nx.articulation_points(undirected):
            # What would lose connectivity if this node failed?
            g_cut = undirected.copy()
            g_cut.remove_node(ap)
            components_after = list(nx.connected_components(g_cut))
            if len(components_after) <= pre_components:
                continue
            # The smaller components are the isolated-by-removal set
            largest = max(components_after, key=len)
            isolated = []
            for comp in components_after:
                if comp is largest:
                    continue
                isolated.extend(sorted(comp))
            articulation_list.append({
                "device": ap,
                "would_isolate": isolated,
            })
    except Exception:
        pass

    articulation_list.sort(
        key=lambda r: (-len(r["would_isolate"]), r["device"])
    )

    # Betweenness top-N
    betweenness_top: list[dict[str, Any]] = []
    try:
        bc = nx.betweenness_centrality(undirected, normalized=True)
        for dev, score in sorted(
            bc.items(), key=lambda kv: -kv[1]
        )[:top_n]:
            betweenness_top.append({
                "device": dev,
                "score": round(float(score), 4),
            })
    except Exception:
        pass

    return {
        "status": "success",
        "node_count": n_nodes,
        "articulation_points": articulation_list[:top_n],
        "betweenness_top": betweenness_top,
    }

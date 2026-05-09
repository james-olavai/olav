"""inspect_blast_radius @tool — What-If reachability impact."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

# Eager import to avoid asyncio.gather _ModuleLock deadlocks when
# LangGraph runs multiple inspect_* tools in parallel.
from olav_netops.sim import load_network_model


@tool
def inspect_blast_radius(
    remove_devices: list[str] | None = None,
    remove_links: list[list[str]] | None = None,
) -> dict[str, Any]:
    """
    What-If: simulate device / link failures on the network graph
    and report the connectivity impact.

    Mutates a copy of ``model.graph`` (so the live graph is
    untouched), then computes weakly-connected components +
    isolated nodes.  Use this for "what happens if X fails" or
    "blast radius of removing Y" questions.

    Args:
        remove_devices: List of hostnames to remove from the graph.
            E.g. ``["R3"]`` simulates R3 hard failure.  Optional.
        remove_links: List of link pairs to remove (both directions).
            Each pair is a 2-element list ``["A", "B"]``.  E.g.
            ``[["R2", "R4"]]`` simulates the R2-R4 link going down.
            Optional.

    Returns:
        ``{
            "removed_devices": [...],
            "removed_links": [...],
            "components": [[...], [...]],   # disconnected groups
            "isolated_nodes": [...],         # nodes with no edges
            "connectivity_loss": {...}       # pre vs post component count
         }``

    Example:
        >>> inspect_blast_radius(remove_devices=["R3"])
        {
          "removed_devices": ["R3"],
          "removed_links": [],
          "components": [["R1"], ["R2", "R4", "WAN"], ["SW1"], ["SW2", "Switch"]],
          "isolated_nodes": ["R1", "SW1"],
          "connectivity_loss": {"pre_components": 1, "post_components": 4},
        }
    """
    import networkx as nx
    model = load_network_model()

    g = model.graph.copy()
    pre_components = nx.number_weakly_connected_components(g)

    removed_devices = remove_devices or []
    removed_links = remove_links or []

    for d in removed_devices:
        if d in g.nodes:
            g.remove_node(d)
    for pair in removed_links:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        u, v = pair
        if g.has_edge(u, v):
            g.remove_edge(u, v)
        if g.has_edge(v, u):
            g.remove_edge(v, u)

    components = sorted(
        [sorted(c) for c in nx.weakly_connected_components(g)],
        key=lambda c: (-len(c), c[0] if c else ""),
    )
    isolated = sorted(n for n in g.nodes if g.degree(n) == 0)

    return {
        "removed_devices": removed_devices,
        "removed_links": removed_links,
        "components": components,
        "isolated_nodes": isolated,
        "connectivity_loss": {
            "pre_components": pre_components,
            "post_components": len(components),
        },
    }

import json
import logging
import sys
from pathlib import Path

import networkx as nx
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core graph logic
# ---------------------------------------------------------------------------

def _build_graph(topology: list[dict]) -> nx.Graph:
    G = nx.Graph()
    for link in topology:
        src = link.get("device") or link.get("src")
        dst = link.get("neighbor") or link.get("dst")
        if src and dst and src != dst:
            G.add_edge(src, dst)
    return G


def _find_path(G: nx.Graph, source: str | None, destination: str | None) -> dict:
    if not source or not destination:
        return {"status": "error", "message": "source and destination required"}
    if source not in G or destination not in G:
        missing = [n for n in [source, destination] if n not in G]
        return {"status": "error", "message": f"Nodes not found: {missing}"}
    try:
        path = nx.shortest_path(G, source, destination)
        return {"status": "success", "source": source, "destination": destination,
                "path": path, "hops": len(path) - 1}
    except nx.NetworkXNoPath:
        return {"status": "success", "source": source, "destination": destination,
                "path": None, "message": "No path exists"}


def _detect_loops(G: nx.Graph) -> dict:
    cycles = list(nx.cycle_basis(G))
    return {"status": "success", "loops_found": len(cycles), "loops": cycles}


def _get_connected(G: nx.Graph, device: str | None) -> dict:
    if not device or device not in G:
        return {"status": "error", "message": f"Device not found: {device}"}
    neighbors = list(G.neighbors(device))
    return {"status": "success", "device": device,
            "connected_devices": neighbors, "connection_count": len(neighbors)}


# ---------------------------------------------------------------------------
# LangChain tool
# ---------------------------------------------------------------------------

@tool
def analyze_network_topology(
    topology: list[dict],
    intent: str = "path",
    source: str | None = None,
    destination: str | None = None,
) -> dict:
    """Analyze network topology using NetworkX graph algorithms.

    Args:
        topology: List of links, each dict with keys 'src'/'device' and 'dst'/'neighbor'.
        intent: "path" (default), "loop_detection", or "connectivity"
        source: Start device for pathfinding / connectivity
        destination: End device for pathfinding

    Returns:
        Analysis results including paths, loops, or connectivity status.
    """
    try:
        G = _build_graph(topology)
        if G.number_of_nodes() == 0:
            return {"status": "error", "message": "No devices"}
        if intent == "path":
            return _find_path(G, source, destination)
        elif intent == "loop_detection":
            return _detect_loops(G)
        elif intent == "connectivity":
            return _get_connected(G, source)
        else:
            return {"status": "error", "message": f"Unknown intent: {intent}"}
    except Exception as e:
        logger.error("Topology analysis failed: %s", e)
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    input_data = json.loads(sys.stdin.read())
    result = analyze_network_topology.invoke(input_data)
    print(json.dumps(result, ensure_ascii=False))

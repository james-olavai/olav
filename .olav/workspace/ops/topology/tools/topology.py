
import sys
from pathlib import Path


# Add src to path
def _find_project_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()

sys.path.insert(0, str(_find_project_root() / "src"))

from langchain_core.tools import tool

from olav.core.memory.topology import analyze_network_topology as _analyze


@tool
def analyze_network_topology(
    topology: list[dict],
    intent: str = "path",
    source: str | None = None,
    destination: str | None = None,
) -> dict:
    """Analyze network topology using DuckDB and DuckPGQ.
    
    This tool performs graph analysis on the provided topology links.
    
    Args:
        topology: List of links, each dict with:
                 (source, destination, [local_interface], [neighbor_interface])
        intent: Analysis type: "path" (default), "loops", or "connectivity"
        source: Start device for pathfinding
        destination: End device for pathfinding
        
    Returns:
        Analysis results including paths, loops, or connectivity status.
    """
    return _analyze(topology, intent=intent, source=source, destination=destination)

if __name__ == "__main__":
    import json
    input_data = json.loads(sys.stdin.read())
    result = analyze_network_topology.invoke(input_data)
    print(json.dumps(result, ensure_ascii=False))

"""Network Topology Analysis Module using DuckPGQ."""

import logging
from collections import defaultdict, deque

import duckdb

logger = logging.getLogger(__name__)


def analyze_network_topology(
    topology: list[dict],
    intent: str = "path",
    source: str | None = None,
    destination: str | None = None,
) -> dict:
    """Analyze network topology based on intent."""
    conn = duckdb.connect()
    try:
        conn.execute("LOAD duckpgq")

        # Build tables
        devices = set()
        links_data = []
        for link in topology:
            device = link.get("device")
            neighbor = link.get("neighbor")
            if device and neighbor:
                devices.add(device)
                devices.add(neighbor)
                links_data.append((device, neighbor))

        if not devices:
            return {"status": "error", "message": "No devices"}

        # Create temp tables
        device_rows = " UNION ALL ".join(f"SELECT '{d}' AS id" for d in devices)
        conn.execute(f"CREATE TEMP TABLE devices AS {device_rows}")

        links_rows = " UNION ALL ".join(
            f"SELECT '{s}' AS source, '{d}' AS dest" for s, d in links_data
        )
        conn.execute(f"CREATE TEMP TABLE links AS {links_rows}")

        # Create property graph
        conn.execute("""
            CREATE PROPERTY GRAPH topo
            VERTEX TABLES (devices)
            EDGE TABLES (
                links SOURCE KEY (source) REFERENCES devices (id)
                      DESTINATION KEY (dest) REFERENCES devices (id)
                      LABEL link
            )
        """)

        if intent == "path":
            return _find_path(conn, source, destination)
        elif intent == "loop_detection":
            return _detect_loops(conn)
        elif intent == "connectivity":
            return _get_connected(conn, source)
        else:
            return {"status": "error", "message": f"Unknown intent: {intent}"}

    except Exception as e:
        logger.error(f"Topology analysis failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


def _find_path(conn, source: str, destination: str) -> dict:
    result = conn.execute("""
        FROM GRAPH_TABLE (topo
            MATCH (a:devices)-[link:link]->(b:devices)
            COLUMNS (a.id AS src, b.id AS dst)
        )
    """).fetchall()

    adj = defaultdict(set)
    for src, dst in result:
        adj[src].add(dst)
        adj[dst].add(src)

    queue = deque([(source, [source])])
    visited = {source}

    while queue:
        curr, path = queue.popleft()
        if curr == destination:
            return {
                "status": "success",
                "source": source,
                "destination": destination,
                "path": path,
                "hops": len(path) - 1,
            }

        for neighbor in adj.get(curr, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

    return {
        "status": "success",
        "source": source,
        "destination": destination,
        "path": None,
        "message": "No path exists",
    }


def _detect_loops(conn) -> dict:
    result = conn.execute("""
        FROM GRAPH_TABLE (topo
            MATCH (a:devices)-[l:link]->(b:devices)
            COLUMNS (a.id AS source, b.id AS dest)
        )
    """).fetchall()

    adj = defaultdict(set)
    for src, dst in result:
        adj[src].add(dst)
        adj[dst].add(src)

    def find_cycles(graph, node, visited, path):
        visited.add(node)
        path.append(node)
        cycles = []

        for neighbor in graph.get(node, []):
            if neighbor in path:
                idx = path.index(neighbor)
                if len(path[idx:]) > 2:
                    cycles.append(path[idx:])
            elif neighbor not in visited:
                cycles.extend(find_cycles(graph, neighbor, visited, path[:]))

        return cycles

    all_cycles = []
    for node in adj:
        if len(adj[node]) >= 2:
            all_cycles.extend(find_cycles(adj, node, set(), []))

    unique = []
    seen = set()
    for c in all_cycles:
        key = tuple(sorted(c))
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return {"status": "success", "loops_found": len(unique), "loops": unique}


def _get_connected(conn, device: str) -> dict:
    result = conn.execute(f"""
        FROM GRAPH_TABLE (topo
            MATCH (a:devices)-[link:link]->(b:devices)
            WHERE a.id = '{device}'
            COLUMNS (b.id AS neighbor)
        )
    """).fetchall()

    neighbors = [r[0] for r in result]

    return {
        "status": "success",
        "device": device,
        "connected_devices": neighbors,
        "connection_count": len(neighbors),
    }

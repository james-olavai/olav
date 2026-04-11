"""Unified Knowledge Store — Knowledge Graph Module.

Materializes the LanceDB vector space into an explicit graph structure
for visualization and export. The underlying store itself acts as the
dynamic graph; this module produces snapshots for Obsidian/vis.js export.

Functions:
    materialize_graph()    Build nodes+edges dict from current LanceDB state.
    export_obsidian()      Write Obsidian vault markdown + frontmatter + wikilinks.
    export_visjs()         Write interactive vis.js HTML graph.
    cluster_knowledge()    Optional Leiden community detection (graspologic).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from olav.core.memory import LanceDBStore

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_ORIGIN_COLORS = {
    "agent": "#4A90D9",
    "document": "#7ED321",
    "user": "#F5A623",
    "audit": "#BD10E0",
}


def _deduplicate_edges(edges: list[dict]) -> list[dict]:
    """Remove duplicate edges (same source+target regardless of order)."""
    seen: set[frozenset] = set()
    result = []
    for e in edges:
        key = frozenset([e["source"], e["target"]])
        if key not in seen:
            seen.add(key)
            result.append(e)
    return result


def _get_community(node_id: str, communities: dict | None) -> int:
    if not communities:
        return 0
    for comm_id, members in communities.items():
        if node_id in members:
            return comm_id
    return 0


def _community_colors(communities: dict | None) -> dict:
    if not communities:
        return {}
    palette = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12",
               "#9b59b6", "#1abc9c", "#e67e22", "#34495e"]
    return {
        comm_id: {"color": palette[i % len(palette)]}
        for i, comm_id in enumerate(communities.keys())
    }


# ─────────────────────────────────────────────────────────────────────────────
# materialize_graph
# ─────────────────────────────────────────────────────────────────────────────

def materialize_graph(
    store: "LanceDBStore",
    similarity_threshold: float = 0.5,
    max_similar_edges: int = 3,
    table_name: str | None = None,
) -> dict:
    """Materialize the LanceDB knowledge store as an explicit graph.

    Produces memory nodes + entity nodes connected by:
    - **Implicit edges** (type='similar'): vector cosine similarity above threshold.
    - **Explicit edges** (type='tagged'): shared tag co-occurrence.

    Args:
        store:               LanceDBStore instance.
        similarity_threshold: Distance cutoff for implicit edges (lower = more similar).
                              0.0 disables similarity edges, 1.0 includes all pairs.
        max_similar_edges:   Maximum similar edges per node.
        table_name:          Optional table override.

    Returns:
        {"nodes": [...], "edges": [...], "entities": {tag: [id,...]}}
    """
    from olav.core.memory import MEMORY_TABLE

    tname = table_name or MEMORY_TABLE

    if not store.table_exists(tname):
        return {"nodes": [], "edges": [], "entities": {}}

    memories = store.get_memories(limit=10_000, table_name=tname)

    nodes: list[dict] = []
    edges: list[dict] = []
    entities: dict[str, list[str]] = {}

    # First pass: build nodes + entity index + explicit (tagged) edges
    for mem in memories:
        mem_id = mem.get("id", "")
        if not mem_id:
            continue

        nodes.append({
            "id": mem_id,
            "label": (mem.get("text") or "")[:60],
            "full_text": mem.get("text", ""),
            "origin": mem.get("origin", "agent"),
            "category": mem.get("category", "fact"),
            "confidence": float(mem.get("confidence") or 0.5),
            "access_count": int(mem.get("access_count") or 0),
        })

        tags = []
        try:
            tags = json.loads(mem.get("tags") or "[]")
        except Exception:
            pass
        for tag in tags:
            entities.setdefault(tag, []).append(mem_id)

    # Second pass: similarity edges (needs vectors — fetch via search_by_vector)
    if similarity_threshold > 0.0:
        # Re-fetch with vector data via search_by_vector (which includes vector)
        for mem in memories:
            mem_id = mem.get("id", "")
            if not mem_id:
                continue
            vector = mem.get("vector")
            if vector is None:
                continue
            try:
                similar = store.search_by_vector(
                    query_vector=list(vector),
                    limit=max_similar_edges + 1,
                    table_name=tname,
                )
            except Exception:
                continue
            for s in similar:
                if s["id"] != mem_id:
                    dist = s.get("score")
                    if dist is None:
                        dist = 1.0
                    if dist < similarity_threshold:
                        edges.append({
                            "source": mem_id,
                            "target": s["id"],
                            "type": "similar",
                            "weight": round(1.0 - dist, 3),
                        })

    # Entity nodes + entity edges
    entity_nodes: list[dict] = []
    for tag, mem_ids in entities.items():
        entity_id = f"entity_{tag}"
        entity_nodes.append({
            "id": entity_id,
            "label": tag,
            "type": "entity",
            "reference_count": len(mem_ids),
        })
        for mid in mem_ids:
            edges.append({
                "source": mid,
                "target": entity_id,
                "type": "tagged",
                "weight": 1.0,
            })

    return {
        "nodes": nodes + entity_nodes,
        "edges": _deduplicate_edges(edges),
        "entities": entities,
    }


# ─────────────────────────────────────────────────────────────────────────────
# export_obsidian
# ─────────────────────────────────────────────────────────────────────────────

def export_obsidian(
    store: "LanceDBStore",
    output_dir: Path,
    communities: dict | None = None,
    table_name: str | None = None,
) -> dict:
    """Export knowledge store as an Obsidian vault.

    Each memory → one .md file with YAML frontmatter + wikilinks.
    Each unique tag → one entity index page under _entities/.

    Args:
        store:       LanceDBStore instance.
        output_dir:  Root directory for the Obsidian vault.
        communities: Optional {community_id: [node_id,...]} from cluster_knowledge().
        table_name:  Optional table override.

    Returns:
        {"written": int, "entities": int}
    """
    def _safe_tag(t: str) -> str:
        """Sanitize a tag string for use as a filesystem path component."""
        return t.replace("/", "_").replace("\\", "_").replace(":", "_").replace(" ", "_")

    from olav.core.memory import MEMORY_TABLE

    tname = table_name or MEMORY_TABLE
    output_dir = Path(output_dir)

    if not store.table_exists(tname):
        return {"written": 0, "entities": 0}

    memories = store.get_memories(limit=10_000, table_name=tname)
    entity_map: dict[str, list[dict]] = {}
    written = 0
    written_paths: dict[str, str] = {}  # mem_id → relative path (for sync state)

    for mem in memories:
        mem_id = mem.get("id", "")
        if not mem_id:
            continue

        tags = []
        try:
            tags = json.loads(mem.get("tags") or "[]")
        except Exception:
            pass

        # Determine subdirectory
        origin = mem.get("origin") or "agent"
        if communities:
            comm_id = _get_community(mem_id, communities)
            subdir = f"community_{comm_id}"
        else:
            subdir = origin

        out_path = output_dir / subdir / f"{mem_id}.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        wikilinks = "\n".join(f"- [[entity_{_safe_tag(t)}|{t}]]" for t in tags) if tags else ""
        related_section = f"\n## Related\n{wikilinks}" if wikilinks else ""

        content = (
            f"---\n"
            f"id: {mem_id}\n"
            f"origin: {origin}\n"
            f"category: {mem.get('category', 'fact')}\n"
            f"confidence: {float(mem.get('confidence') or 0.5)}\n"
            f"tags: {json.dumps(tags)}\n"
            f"access_count: {int(mem.get('access_count') or 0)}\n"
            f"---\n\n"
            f"{mem.get('text', '')}"
            f"{related_section}\n"
        )
        out_path.write_text(content, encoding="utf-8")
        written += 1
        written_paths[mem_id] = str(out_path.relative_to(output_dir))

        for tag in tags:
            entity_map.setdefault(tag, []).append(mem)

    # Entity index pages
    entities_dir = output_dir / "_entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    for tag, mems in entity_map.items():
        ent_path = entities_dir / f"entity_{_safe_tag(tag)}.md"
        links = "\n".join(
            f"- [[{m['id']}]] — {(m.get('text') or '')[:60]}"
            for m in mems
        )
        ent_path.write_text(
            f"# {tag}\n\n{len(mems)} entries reference this entity.\n\n{links}\n",
            encoding="utf-8",
        )

    # Populate sync state so `olav kb sync` recognises exported files as already tracked
    if written_paths:
        try:
            import hashlib as _hashlib
            import json as _json

            def _fhash(p: Path) -> str:
                return _hashlib.md5(p.read_bytes()).hexdigest()

            state_path = output_dir / ".olav_sync_state.json"
            state = {
                rel: {"hash": _fhash(output_dir / rel), "ids": [mem_id]}
                for mem_id, rel in written_paths.items()
            }
            state_path.write_text(_json.dumps(state, indent=2))
        except Exception as _e:
            logger.warning(f"export_obsidian: could not write sync state: {_e}")

    logger.info(f"export_obsidian: wrote {written} notes, {len(entity_map)} entity pages → {output_dir}")
    return {"written": written, "entities": len(entity_map)}


# ─────────────────────────────────────────────────────────────────────────────
# vis.js export
# ─────────────────────────────────────────────────────────────────────────────

_VIS_TEMPLATE = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>OLAV Knowledge Graph</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  body{margin:0;font-family:sans-serif}
  #graph{width:100vw;height:100vh}
  #controls{position:fixed;top:10px;left:10px;background:rgba(255,255,255,0.9);padding:8px;border-radius:4px}
  select{margin:2px}
</style>
</head><body>
<div id="controls">
  Origin:
  <select id="origin-filter" onchange="filterGraph()">
    <option value="">All</option>
    <option value="agent">Agent</option>
    <option value="document">Document</option>
    <option value="user">User</option>
    <option value="audit">Audit</option>
  </select>
</div>
<div id="graph"></div>
<script>
var ALL_NODES = /*NODES_JSON*/;
var ALL_EDGES = /*EDGES_JSON*/;
var options = {
  nodes:{shape:"dot",font:{size:12}},
  edges:{smooth:{type:"continuous"},arrows:{to:{enabled:false}}},
  physics:{solver:"forceAtlas2Based"},
  groups: /*GROUPS_JSON*/
};
var nodes = new vis.DataSet(ALL_NODES);
var edges = new vis.DataSet(ALL_EDGES);
var network = new vis.Network(document.getElementById("graph"),{nodes,edges},options);
function filterGraph(){
  var origin = document.getElementById("origin-filter").value;
  var filtered = origin ? ALL_NODES.filter(function(n){return n.origin===origin||n.type==="entity";}) : ALL_NODES;
  nodes.clear(); nodes.add(filtered);
}
</script></body></html>
"""


def export_visjs(
    graph_data: dict,
    output_path: Path,
    communities: dict | None = None,
) -> None:
    """Write an interactive vis.js HTML knowledge graph.

    Args:
        graph_data:   Output from materialize_graph().
        output_path:  Target .html file path.
        communities:  Optional community map from cluster_knowledge().
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    vis_nodes = []
    for n in graph_data.get("nodes", []):
        vis_nodes.append({
            "id": n["id"],
            "label": n.get("label", n["id"])[:40],
            "title": n.get("full_text", n.get("label", n["id"])),
            "group": _get_community(n["id"], communities),
            "size": 5 + int(n.get("access_count") or 0),
            "origin": n.get("origin", ""),
            "type": n.get("type", "memory"),
            "color": _ORIGIN_COLORS.get(n.get("origin", ""), "#aaaaaa"),
        })

    vis_edges = []
    for e in graph_data.get("edges", []):
        vis_edges.append({
            "from": e["source"],
            "to": e["target"],
            "value": e.get("weight", 0.5),
            "title": e.get("type", ""),
            "dashes": e.get("type") == "similar",
        })

    html = _VIS_TEMPLATE
    html = html.replace("/*NODES_JSON*/", json.dumps(vis_nodes))
    html = html.replace("/*EDGES_JSON*/", json.dumps(vis_edges))
    html = html.replace("/*GROUPS_JSON*/", json.dumps(_community_colors(communities)))

    output_path.write_text(html, encoding="utf-8")
    logger.info(f"export_visjs: wrote {len(vis_nodes)} nodes, {len(vis_edges)} edges → {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Optional Leiden clustering
# ─────────────────────────────────────────────────────────────────────────────

def cluster_knowledge(graph_data: dict) -> dict[int, list[str]] | None:
    """Optional Leiden community detection on the materialized graph.

    Requires ``graspologic`` and ``networkx`` to be installed.
    Returns None gracefully if either is unavailable or the graph is too small.

    Args:
        graph_data: Output from materialize_graph().

    Returns:
        {community_id: [node_id, ...]} or None.
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    if len(nodes) < 3:
        return None

    try:
        import networkx as nx  # type: ignore
        from graspologic.partition import leiden  # type: ignore
    except (ImportError, Exception):
        return None

    G = nx.Graph()
    for n in nodes:
        G.add_node(n["id"])
    for e in edges:
        G.add_edge(e["source"], e["target"], weight=e.get("weight", 1.0))

    if len(G) < 3:
        return None

    try:
        partition = leiden(G)
    except Exception as exc:
        logger.debug(f"cluster_knowledge: leiden failed: {exc}")
        return None

    communities: dict[int, list[str]] = {}
    for node_id, comm_id in partition.items():
        communities.setdefault(comm_id, []).append(node_id)

    return communities

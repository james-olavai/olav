#!/usr/bin/env python3
"""
Topology Sandbox Tool - NetworkX-powered graph analysis (Phase 5).

Replaces the YAML-strategy-based generate_topology.py with a direct
LLMExperimentSandbox execution that:
  1. Queries v_topo_links_clean (or topology_links fallback)
  2. Builds a NetworkX MultiGraph (SPLIT_PART strips .local at SQL level)
  3. Runs graph algorithms: shortest path, cut-points, degree centrality
  4. Emits a Mermaid diagram saved to agent_outputs/

Sandbox contract: set ``_result = { ... }`` — executor serialises via json.dumps.
DO NOT use print() for result passing (corrupts stdout -> JSON parse fails).

Validated (2026-03-04):
  - NetworkX: 0.5ms build, 7 nodes, 23 edges, all algorithms OK
  - DuckPGQ 1.4.3: Views unsupported + SHORTEST PATH syntax missing - rejected
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

from olav.core.config import MAIN_DB_PATH
from olav.core.simulation.llm_sandbox import LLMExperimentSandbox

# ---------------------------------------------------------------------------
# Experiment template — placeholders: {db_path}, {snapshot_id}, {src_node},
# {dst_node}. All literal braces inside MUST be doubled {{ }} because .format()
# is used for substitution.
# ---------------------------------------------------------------------------
_TOPO_EXPERIMENT = """\
import duckdb
import networkx as nx

DB_PATH  = {db_path!r}
SNAP_ID  = {snapshot_id!r}
SRC_NODE = {src_node!r}
DST_NODE = {dst_node!r}

con = duckdb.connect(DB_PATH)
q = ("SELECT src, dst, discovery_protocol, link_type, link_status "
     "FROM v_topo_links_clean")
params = []
if SNAP_ID:
    q += " WHERE snapshot_id = ?"
    params = [SNAP_ID]
edges = con.execute(q, params).fetchall()
con.close()

# ── Layer-separated graphs ────────────────────────────────────────────────
# Physical substrate (L2: CDP / LLDP) is the foundation.
# Logical overlay (L3: OSPF / BGP) rides on top of the physical layer.
G_l2  = nx.MultiGraph()   # physical layer
G_l3  = nx.MultiGraph()   # logical layer
G_all = nx.MultiGraph()   # combined (for full reachability)

for src, dst, proto, ltype, status in edges:
    if not src or not dst or src == dst:
        continue
    attrs = dict(protocol=(proto or "UNKNOWN"), link_type=(ltype or "L2"), status=(status or "up"))
    G_all.add_edge(src, dst, **attrs)
    if (ltype or "").upper() == "L2":
        G_l2.add_edge(src, dst, **attrs)
    else:
        G_l3.add_edge(src, dst, **attrs)

# ── Physical-layer analysis (foundation) ─────────────────────────────────
nodes_l2     = list(G_l2.nodes())
l2_connected = nx.is_connected(G_l2) if nodes_l2 else False
cut_nodes    = sorted(nx.articulation_points(G_l2)) if l2_connected else []
centrality   = dict(sorted(nx.degree_centrality(G_l2).items(), key=lambda x: -x[1]))

# ── Combined graph for full reachability ─────────────────────────────────
nodes_all    = list(G_all.nodes())
all_connected = nx.is_connected(G_all) if nodes_all else False

# ── Shortest path: L2-only first, then combined fallback ─────────────────
path       = None
path_layer = None
path_error = None
if SRC_NODE and DST_NODE:
    if SRC_NODE not in G_all or DST_NODE not in G_all:
        missing = [n for n in [SRC_NODE, DST_NODE] if n not in G_all]
        path_error = "Nodes not found: " + str(missing)
    else:
        # Prefer L2 physical path
        if SRC_NODE in G_l2 and DST_NODE in G_l2:
            try:
                path = nx.shortest_path(G_l2, SRC_NODE, DST_NODE)
                path_layer = "L2"
            except nx.NetworkXNoPath:
                pass
        if path is None:
            # Fall back to combined graph (crosses L3 links)
            try:
                path = nx.shortest_path(G_all, SRC_NODE, DST_NODE)
                path_layer = "combined"
            except nx.NetworkXNoPath:
                path_error = "No path between " + repr(SRC_NODE) + " and " + repr(DST_NODE)

# ── Mermaid: L2 edges solid, L3 edges dashed ─────────────────────────────
mermaid_lines = ["graph LR"]
seen = set()
for u, v, d in G_all.edges(data=True):
    k = (min(u,v), max(u,v), d.get("protocol","?"))
    if k not in seen:
        label = d.get("protocol", "?")
        arrow = "-->" if (d.get("link_type","L2").upper() == "L2") else "-.->"
        mermaid_lines.append("    " + u + " " + arrow + "|" + label + "| " + v)
        seen.add(k)
mermaid = "\\n".join(mermaid_lines)

_result = {{
    "nodes":             sorted(nodes_all),
    "node_count":        len(nodes_all),
    "edge_count":        G_all.number_of_edges(),
    "l2_edge_count":     G_l2.number_of_edges(),
    "l3_edge_count":     G_l3.number_of_edges(),
    "l2_nodes":          sorted(nodes_l2),
    "l3_nodes":          sorted(list(G_l3.nodes())),
    "l2_connected":      l2_connected,
    "all_connected":     all_connected,
    "cut_points":        cut_nodes,
    "l2_degree_centrality": centrality,
    "shortest_path":     path,
    "shortest_path_layer": path_layer,
    "path_error":        path_error,
    "mermaid":           mermaid,
    "data_source":       "v_topo_links_clean",
}}
"""


class TopologySandboxInput(BaseModel):
    """Input for topology sandbox analysis."""

    snapshot_id: str | None = Field(
        default=None,
        description="Snapshot ID to analyse. If None, uses all available data.",
    )
    src_node: str | None = Field(
        default=None,
        description="Source device for shortest-path query (e.g. 'R1').",
    )
    dst_node: str | None = Field(
        default=None,
        description="Destination device for shortest-path query (e.g. 'SW2').",
    )
    save_mermaid: bool = Field(
        default=True,
        description="Save Mermaid diagram to agent_outputs/network_topology.mmd",
    )


@tool(args_schema=TopologySandboxInput)
def run_topology_sandbox(
    snapshot_id: str | None = None,
    src_node: str | None = None,
    dst_node: str | None = None,
    save_mermaid: bool = True,
) -> dict[str, Any]:
    """Analyse network topology using NetworkX graph algorithms.

    Builds a MultiGraph from topology_links (via v_topo_links_clean), then:
      - Lists all nodes and edges
      - Checks full connectivity
      - Identifies critical nodes (articulation points / cut-points)
      - Ranks nodes by degree centrality
      - Optionally computes shortest path between two named devices
      - Generates and saves a Mermaid diagram

    Returns: nodes, node_count, edge_count, l2_edge_count, l3_edge_count,
    l2_connected, all_connected, cut_points (based on L2 physical graph),
    l2_degree_centrality, shortest_path (L2-first, combined fallback),
    shortest_path_layer, path_error, mermaid, data_source.
    """
    project_root = _find_project_root()
    db_path = str(MAIN_DB_PATH)

    code = _TOPO_EXPERIMENT.format(
        db_path=db_path,
        snapshot_id=snapshot_id or "",
        src_node=src_node or "",
        dst_node=dst_node or "",
    )

    sandbox = LLMExperimentSandbox(
        db_path=db_path,
        work_dir=str(project_root / "tmp" / "topology_sandbox"),
    )

    # Check for a running event loop before creating any coroutine to avoid
    # "coroutine was never awaited" warnings when called from async contexts.
    try:
        asyncio.get_running_loop()
        _has_running_loop = True
    except RuntimeError:
        _has_running_loop = False

    if _has_running_loop:
        # Already inside a running event loop (e.g. onboard async context).
        # Run in a worker thread with its own event loop.
        import concurrent.futures

        def _run_in_thread() -> object:
            return asyncio.run(
                sandbox.execute_experiment(
                    experiment_code=code,
                    experiment_name="topology_analysis",
                    timeout=60,
                )
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            result_obj = pool.submit(_run_in_thread).result(timeout=120)
    else:
        result_obj = asyncio.run(
            sandbox.execute_experiment(
                experiment_code=code,
                experiment_name="topology_analysis",
                timeout=60,
            )
        )

    # result_obj.result holds the dict set via _result in the experiment
    topo_data: dict[str, Any] = result_obj.result or {}

    if not isinstance(topo_data, dict) or "nodes" not in topo_data:
        err = topo_data if isinstance(topo_data, dict) else {}
        return {
            "status": "error",
            "error": err.get("error", "Sandbox returned unexpected result"),
            "trace": err.get("trace", ""),
            "sandbox_status": result_obj.status,
        }

    # Persist Mermaid diagram
    if save_mermaid and topo_data.get("mermaid"):
        out_path = project_root / "exports" / "agent_outputs" / "network_topology.mmd"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(topo_data["mermaid"] + "\n", encoding="utf-8")
        topo_data["mermaid_saved_to"] = str(out_path)

    # ── Persist as DuckDB-queryable JSONL ─────────────────────────────────────
    # Agents can query these directly:  SELECT * FROM read_json_auto('...')
    # No DDL needed — DuckDB infers schema at read time.
    analysed_at = datetime.now(UTC).isoformat()
    topo_analysis_dir = MAIN_DB_PATH.parent / "topology_analysis"
    topo_analysis_dir.mkdir(parents=True, exist_ok=True)

    # topo_meta_latest.jsonl — one row: snapshot-level summary
    meta_record = {
        "analysed_at":   analysed_at,
        "snapshot_id":   snapshot_id or "",
        "node_count":    topo_data.get("node_count"),
        "edge_count":    topo_data.get("edge_count"),
        "is_connected":  topo_data.get("is_connected"),
        "cut_points":    topo_data.get("cut_points", []),
        "src_node":      src_node or "",
        "dst_node":      dst_node or "",
        "shortest_path": topo_data.get("shortest_path"),
        "path_error":    topo_data.get("path_error"),
        "data_source":   topo_data.get("data_source"),
    }
    meta_path = topo_analysis_dir / "topo_meta_latest.jsonl"
    meta_path.write_text(json.dumps(meta_record) + "\n", encoding="utf-8")
    topo_data["meta_jsonl"] = str(meta_path)

    # topo_nodes_latest.jsonl — one row per node (degree centrality, cut-point flag)
    cut_set = set(topo_data.get("cut_points") or [])
    centrality = topo_data.get("degree_centrality") or {}
    node_lines = [
        json.dumps({
            "analysed_at":       analysed_at,
            "node":              node,
            "degree_centrality": centrality.get(node),
            "is_cut_point":      node in cut_set,
        })
        for node in sorted(topo_data.get("nodes") or [])
    ]
    nodes_path = topo_analysis_dir / "topo_nodes_latest.jsonl"
    nodes_path.write_text("\n".join(node_lines) + "\n", encoding="utf-8")
    topo_data["nodes_jsonl"] = str(nodes_path)

    topo_data["status"] = "success"
    return topo_data

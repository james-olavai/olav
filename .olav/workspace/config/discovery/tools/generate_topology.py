#!/usr/bin/env python3
"""
Topology Generation Tool - Build bidirectional, deduplicated topology links.

This tool generates unified topology from normalized tables:
1. Physical links from CDP/LLDP neighbors (bidirectional edges)
2. Logical links from BGP/OSPF neighbors

The algorithm ensures:
- Bidirectional edge normalization (A->B and B->A become single link)
- Deduplication (no duplicate edges)
- Logical overlay on top of physical

Usage:
    generate_topology(snapshot_id="20260226_120000")
"""

import json
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


def _find_project_root() -> Path:
    """Locate project root."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

import duckdb

from olav.core.config import MAIN_DB_PATH


class TopologyInput(BaseModel):
    """Input for topology generation."""

    snapshot_id: str = Field(..., description="Snapshot ID to generate topology for")


class TopologyOutput(BaseModel):
    """Output from topology generation."""

    status: str = Field(..., description="success | error")
    physical_links: int = Field(default=0, description="Number of physical links created")
    logical_links: int = Field(default=0, description="Number of logical links created")
    total_links: int = Field(default=0, description="Total unique links")
    message: str | None = Field(default=None, description="Additional information")
    error: str | None = Field(default=None, description="Error message if status=error")


def _get_skill_root() -> Path:
    """Locate the root of this skill."""
    return Path(__file__).resolve().parent.parent

def _load_strategy() -> dict:
    """Load topology strategy from the skill's config directory."""
    import yaml
    config_path = _get_skill_root() / "config" / "topology_strategy.yaml"
    if not config_path.exists():
        return {}
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data.get("topology_strategy", {})
    except Exception as e:
        print(f"Warning: Failed to load baselines.yaml for topology: {e}")
        return {}

def _fetch_source_data(source_config: dict, snapshot_id: str) -> list[dict]:
    """Fetch data from a source table based on config."""
    table = source_config.get("table")
    mappings = source_config.get("mappings", {})
    filter_expr = source_config.get("filter", "1=1")
    
    with duckdb.connect(str(MAIN_DB_PATH)) as conn:
        try:
            # Check if table exists
            exists = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", 
                [table]
            ).fetchone()[0]
            
            if not exists:
                return []
            
            sql = f"SELECT * FROM {table} WHERE {filter_expr} AND snapshot_id = ?"
            result = conn.execute(sql, [snapshot_id]).fetchall()
            if not result:
                return []
            
            cols = [d[0] for d in conn.execute(f"DESCRIBE {table}").fetchall()]
            raw_rows = [dict(zip(cols, r)) for r in result]
            
            # Apply mappings
            normalized_rows = []
            for row in raw_rows:
                norm = {}
                for target_key, source_key in mappings.items():
                    if source_key.startswith("CONSTANT:"):
                        norm[target_key] = source_key.split(":", 1)[1]
                    else:
                        norm[target_key] = row.get(source_key, "")
                normalized_rows.append(norm)
            return normalized_rows
        except Exception as e:
            print(f"Warning: Failed to fetch from {table}: {e}")
            return []

def _normalize_device_name(name: str) -> str:
    """Normalize device name for comparison."""
    if not name: return ""
    return name.lower().strip()

def _create_edge_key(source: str, dest: str) -> str:
    """Create normalized bidirectional edge key."""
    s = _normalize_device_name(source)
    d = _normalize_device_name(dest)
    # Sort to ensure A->B and B->A produce same key
    return "|".join(sorted([s, d]))

def _process_links(data: list[dict], link_type: str) -> dict[str, dict]:
    """Process normalized data into edge dictionary."""
    edges = {}
    for item in data:
        src = item.get("source_device")
        dst = item.get("dest_device")
        if not src or not dst: continue
        
        # Physical links use edge sorting for deduplication
        if link_type == "physical":
            key = _create_edge_key(src, dst)
        else:
            # Logical links are often directed or specific to IP
            key = f"logical_{src}_{dst}"
            
        if key not in edges:
            edges[key] = {
                "source": src,
                "dest": dst,
                "source_interface": item.get("source_interface", "N/A"),
                "dest_interface": item.get("dest_interface", "N/A"),
                "discovery_protocol": item.get("protocol", "UNKNOWN"),
                "link_type": link_type,
                "link_status": "up"
            }
    return edges


def _save_topology_links(snapshot_id: str, links: list[dict], target_table: str):
    """Save topology links to database."""
    with duckdb.connect(str(MAIN_DB_PATH)) as conn:
        # Simple schema for unified topology
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {target_table} (
                link_id VARCHAR PRIMARY KEY,
                snapshot_id VARCHAR,
                source_device VARCHAR,
                source_interface VARCHAR,
                dest_device VARCHAR,
                dest_interface VARCHAR,
                discovery_protocol VARCHAR,
                link_type VARCHAR,
                link_status VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Delete existing links for this snapshot
        conn.execute(f"DELETE FROM {target_table} WHERE snapshot_id = ?", [snapshot_id])

        # Insert new links
        for link in links:
            link_id = f"{snapshot_id}_{link['source']}_{link['dest']}_{link['discovery_protocol']}"
            conn.execute(
                f"INSERT INTO {target_table} (link_id, snapshot_id, source_device, source_interface, "
                "dest_device, dest_interface, discovery_protocol, link_type, link_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    link_id,
                    snapshot_id,
                    link["source"],
                    link.get("source_interface", ""),
                    link["dest"],
                    link.get("dest_interface", ""),
                    link.get("discovery_protocol", ""),
                    link.get("link_type", "physical"),
                    link.get("link_status", "up"),
                ],
            )


def main(params: dict) -> dict:
    """Generate topology from normalized tables."""
    try:
        args = TopologyInput(**params)
    except Exception as e:
        return TopologyOutput(status="error", error=f"Invalid parameters: {str(e)}").model_dump(
            exclude_none=True
        )

    snapshot_id = args.snapshot_id

    try:
        # 1. Load Strategy
        strategy = _load_strategy()
        if not strategy:
            return TopologyOutput(status="error", error="Topology strategy not found in config").model_dump(exclude_none=True)

        target_table = strategy.get("target_table", "topology_links")
        sources = strategy.get("sources", {})
        
        all_edges = {}
        physical_count = 0
        logical_count = 0

        # 2. Process Physical Sources
        for src_config in sources.get("physical", []):
            data = _fetch_source_data(src_config, snapshot_id)
            edges = _process_links(data, "physical")
            physical_count += len(edges)
            all_edges.update(edges)

        # 3. Process Logical Sources
        for src_config in sources.get("logical", []):
            data = _fetch_source_data(src_config, snapshot_id)
            edges = _process_links(data, "logical")
            logical_count += len(edges)
            all_edges.update(edges)

        links = list(all_edges.values())

        # 4. Save to database
        _save_topology_links(snapshot_id, links, target_table)

        return TopologyOutput(
            status="success",
            physical_links=physical_count,
            logical_links=logical_count,
            total_links=len(links),
            message=f"Generated {len(links)} links using {target_table} strategy",
        ).model_dump(exclude_none=True)

    except Exception as e:
        import traceback
        return TopologyOutput(status="error", error=f"{str(e)}\n{traceback.format_exc()}").model_dump(exclude_none=True)


# =============================================================================
# LangChain Tool Registration
# =============================================================================


@tool
def generate_topology(snapshot_id: str) -> dict:
    """Generate unified topology links from normalized tables.

    Creates bidirectional, deduplicated physical links from CDP/LLDP,
    then overlays logical links from BGP/OSPF neighbors.

    Args:
        snapshot_id: The snapshot ID to generate topology for

    Returns:
        Dictionary with link counts and status

    Examples:
        >>> generate_topology(snapshot_id="20260226_120000")
    """
    return main({"snapshot_id": snapshot_id})


if __name__ == "__main__":
    try:
        input_str = sys.stdin.read()
        if not input_str:
            input_data = {}
        else:
            input_data = json.loads(input_str)

        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        sys.exit(1)

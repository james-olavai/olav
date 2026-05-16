"""Topology view utilities — filter + Markdown table emission.

``build_adjacencies_view`` queries one of three data sources and emits a
Markdown adjacency table compatible with ``render_topology_mermaid`` and
``render_topology_drawio``:

  * ``l2_cdp``  → ``netops.topology_links``
  * ``bgp``     → ``netops.v_show_ip_bgp_neighbors_auto``
  * ``ospf``    → ``netops.v_show_ip_ospf_neighbor_auto``

Filtering: center+hops BFS, role/site/name_like, snapshot_id.

See ``filter.py`` for the implementation.
"""
from __future__ import annotations

from .filter import (
    PROTOCOL_SOURCES,
    AdjacencyRecord,
    build_adjacencies_view,
    build_device_metadata,
)

__all__ = [
    "AdjacencyRecord",
    "PROTOCOL_SOURCES",
    "build_adjacencies_view",
    "build_device_metadata",
]

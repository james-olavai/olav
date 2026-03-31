"""Topology renderer — LabTopologySpec → ContainerLab topology dict (§14).

All nodes are rendered as SR Linux (kind=srl) regardless of production platform.
SR Linux is the universal digital twin target because it natively supports
OpenConfig via gNMI Set, enabling standardised config push.

Usage:
    from clab_topology_render import render_clab_topology, map_iface_to_srl

    topo_dict = render_clab_topology(spec, lab_name="run-abc123")
    # → pass to CLabClient.deploy(topology_content=topo_dict)
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_LAB_SCRIPTS = _Path(__file__).parent.resolve()
if str(_LAB_SCRIPTS) not in _sys.path:
    _sys.path.insert(0, str(_LAB_SCRIPTS))

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clab_cab import LabTopologySpec

_DEFAULT_SRL_IMAGE = "ghcr.io/nokia/srlinux"

# ---------------------------------------------------------------------------
# Interface name → SRL format
# ---------------------------------------------------------------------------

_ETH_N = re.compile(r"^(?:eth|e|ethernet)(\d+)$", re.IGNORECASE)
_ET_N = re.compile(r"^et(\d+)$", re.IGNORECASE)
_GI_SLASH = re.compile(r"^(?:gi|gigabitethernet)\d+/(\d+)$", re.IGNORECASE)
_ET_DASH = re.compile(r"^et-\d+/\d+/(\d+)$", re.IGNORECASE)
_SRL_ALREADY = re.compile(r"^ethernet-\d+/(\d+)$", re.IGNORECASE)


def map_iface_to_srl(iface_name: str, fallback_index: int = 1) -> str:
    """Map a production interface name to SR Linux ethernet-1/N format.

    Rules (in priority order):
        ethernet-1/N         → pass through
        eth{N}/e{N}/Ethernet{N} → ethernet-1/{N}
        Et{N}                → ethernet-1/{N}  (N treated as port, 0→1)
        Gi{slot}/{N}         → ethernet-1/{N}
        et-{a}/{b}/{c}       → ethernet-1/{c+1}
        fallback             → ethernet-1/{fallback_index}
    """
    if not iface_name:
        return f"ethernet-1/{fallback_index}"

    s = iface_name.strip()

    # Already SRL format
    m = _SRL_ALREADY.match(s)
    if m:
        return s.lower()

    # eth1 / e1 / Ethernet1 / Ethernet2
    m = _ETH_N.match(s)
    if m:
        return f"ethernet-1/{m.group(1)}"

    # Et0 / Et1 — treat as port number, 0 → 1
    m = _ET_N.match(s)
    if m:
        n = int(m.group(1))
        return f"ethernet-1/{max(n, 1)}"

    # Gi0/1, GigabitEthernet0/2
    m = _GI_SLASH.match(s)
    if m:
        return f"ethernet-1/{m.group(1)}"

    # et-0/0/0 (Juniper) → ethernet-1/1; et-0/0/1 → ethernet-1/2
    m = _ET_DASH.match(s)
    if m:
        return f"ethernet-1/{int(m.group(1)) + 1}"

    return f"ethernet-1/{fallback_index}"


# ---------------------------------------------------------------------------
# Interface map derivation from topology spec
# ---------------------------------------------------------------------------


def build_iface_map_from_spec(spec: "LabTopologySpec") -> dict[str, str]:
    """Derive {vendor_iface: srl_ethernet} mapping from a LabTopologySpec.

    Uses the same map_iface_to_srl() heuristic that render_clab_topology()
    uses to assign SRL ethernet-1/N ports in the CLAB YAML, so the config
    pushed to SRL nodes uses the identical interface names.

    Args:
        spec: LabTopologySpec from CLABCABAgent.build_reduced_topology().

    Returns:
        Flat dict: {"GigabitEthernet1": "ethernet-1/1", "Gi0/2": "ethernet-1/2", ...}
    """
    iface_map: dict[str, str] = {}
    for lk in spec.links:
        if lk.source_iface:
            iface_map[lk.source_iface] = map_iface_to_srl(lk.source_iface)
        if lk.target_iface:
            iface_map[lk.target_iface] = map_iface_to_srl(lk.target_iface)
    return iface_map


def build_iface_map_from_links(links: list) -> dict[str, str]:
    """Derive iface_map from any list of link objects (source_interface / destination_interface).

    Works with topology_links rows (dicts or objects) from the DB, as well as
    LabLink objects.  Covers both attribute and dict access patterns.

    Args:
        links: List of link objects or dicts with source/destination interface keys.

    Returns:
        Flat dict: {real_iface_name: srl_ethernet_name}
    """
    iface_map: dict[str, str] = {}
    for lk in links:
        # Support both object attributes and dict keys
        if isinstance(lk, dict):
            src = lk.get("source_interface") or lk.get("source_iface")
            dst = lk.get("destination_interface") or lk.get("target_iface")
        else:
            src = getattr(lk, "source_iface", None) or getattr(lk, "source_interface", None)
            dst = getattr(lk, "target_iface", None) or getattr(lk, "destination_interface", None)
        if src:
            iface_map[src] = map_iface_to_srl(src)
        if dst:
            iface_map[dst] = map_iface_to_srl(dst)
    return iface_map


# ---------------------------------------------------------------------------
# Topology renderer
# ---------------------------------------------------------------------------


def render_clab_topology(
    spec: "LabTopologySpec",
    lab_name: str,
    srl_image: str = _DEFAULT_SRL_IMAGE,
    config_dir: Path | None = None,
) -> dict:
    """Render LabTopologySpec as a CLAB topology dict for CLabClient.deploy().

    Args:
        spec:        Reduced topology from CLABCABAgent.build_reduced_topology().
        lab_name:    Base lab name; output name is ``cab-{lab_name}``.
        srl_image:   SR Linux container image (default: ghcr.io/nokia/srlinux).
        config_dir:  If provided, each node gets a startup-config pointing to
                     ``{config_dir}/{node_name}.cfg``. The caller is responsible
                     for writing those files before deploying.

    Returns:
        Dict suitable for ``CLabClient.deploy(topology_content=...)``.

    Notes:
        - ``prefix: ""`` is mandatory so exec API returns short node names (r1 not clab-lab-r1).
        - All nodes use kind=srl regardless of production platform.
        - Interface names are mapped to SRL format via map_iface_to_srl().
    """
    nodes: dict = {}
    for node in spec.nodes:
        node_cfg: dict = {}
        if config_dir is not None:
            node_cfg["startup-config"] = str(Path(config_dir) / f"{node.name}.cfg")
        nodes[node.name] = node_cfg if node_cfg else {}

    # Build link index: track how many times each (node, direction) is used
    # so that link N → ethernet-1/N mapping is consistent with link order.
    link_iface_counter: dict[str, int] = {}

    def _next_iface(node: str, preferred: str | None) -> str:
        if preferred:
            return map_iface_to_srl(preferred)
        link_iface_counter[node] = link_iface_counter.get(node, 0) + 1
        return f"ethernet-1/{link_iface_counter[node]}"

    links = []
    for lk in spec.links:
        src_iface = _next_iface(lk.source, lk.source_iface)
        dst_iface = _next_iface(lk.target, lk.target_iface)
        links.append({"endpoints": [f"{lk.source}:{src_iface}", f"{lk.target}:{dst_iface}"]})

    return {
        "name": f"cab-{lab_name}",
        "prefix": "",   # container names = node names (no clab-<lab>- prefix)
        "topology": {
            "defaults": {
                "kind": "srl",
                "image": srl_image,
            },
            "nodes": nodes,
            "links": links,
        },
    }

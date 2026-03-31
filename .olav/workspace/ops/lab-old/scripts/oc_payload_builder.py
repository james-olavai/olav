"""ControlPlaneSnapshot → SRL CLI startup config (§15).

Single entry point:
    snapshot_to_srl_config(node_name, snapshot) → str

Direct conversion — no intermediate OC dict.
The snapshot is the source of truth; this module writes SRL set/... commands
from its fields in one pass.

Phase 7 note: if gNMI push is added later, an OC-shaped dict will be needed
as input to gNMI SetRequest. That translation belongs in a separate module.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_LAB_SCRIPTS = _Path(__file__).parent.resolve()
if str(_LAB_SCRIPTS) not in _sys.path:
    _sys.path.insert(0, str(_LAB_SCRIPTS))

import ipaddress
from typing import TYPE_CHECKING

from clab_topology_render import map_iface_to_srl

if TYPE_CHECKING:
    from olav.core.control_plane_ir import ControlPlaneSnapshot


# ---------------------------------------------------------------------------
# Primary: direct snapshot → SRL CLI config (single pass, no OC intermediate)
# ---------------------------------------------------------------------------


def snapshot_to_srl_config(
    node_name: str,
    snapshot: "ControlPlaneSnapshot",
) -> str:
    """Convert a ControlPlaneSnapshot directly to SRL CLI startup config.

    Single-pass: reads snapshot fields (topology_links, bgp_neighbors, routes)
    and emits ``set /...`` commands in one step — no intermediate OC dict.

    Replaces the two-call chain:
        build_oc_payloads({node_name}, snapshot)[node_name]
        + render_srl_startup_cfg(node_name, payload, snapshot)

    Covers:
        - Interfaces (admin-state, subinterface 0, IPv4 address from /30 routes)
        - BGP (local-as, router-id, neighbors with peer-as + transport local-address)
        - network-instance default wiring

    Returns:
        Newline-separated ``set /...`` commands, or ``# no config derived`` comment.
    """
    lines: list[str] = []

    # ── Interfaces ────────────────────────────────────────────────────────
    iface_names: list[str] = []
    seen_ifaces: set[str] = set()

    for link in snapshot.topology_links:
        raw_iface: str | None = None
        if link.source == node_name and link.source_iface:
            raw_iface = link.source_iface
        elif link.target == node_name and link.target_iface:
            raw_iface = link.target_iface
        if raw_iface is None:
            continue
        srl_iface = map_iface_to_srl(raw_iface)
        if srl_iface in seen_ifaces:
            continue
        seen_ifaces.add(srl_iface)
        iface_names.append(srl_iface)

    if iface_names:
        lines.append("# --- interfaces ---")
        for iface in iface_names:
            lines.append(f"set / interface {iface} admin-state enable")
            lines.append(f"set / interface {iface} subinterface 0 admin-state enable")
            lines.append(f"set / interface {iface} subinterface 0 ipv4 admin-state enable")
            ip_cidr = _infer_interface_ip(node_name, iface, snapshot)
            if ip_cidr:
                lines.append(
                    f"set / interface {iface} subinterface 0 ipv4 address {ip_cidr} primary"
                )

    # ── BGP ───────────────────────────────────────────────────────────────
    node_nbrs = [n for n in snapshot.bgp_neighbors if n.device == node_name]

    if node_nbrs:
        local_as = _infer_local_as(node_name, snapshot)
        router_id = _infer_router_id(node_name, snapshot)

        lines.append("# --- BGP ---")
        for iface in iface_names:
            lines.append(f"set / network-instance default interface {iface}.0")

        if local_as:
            lines.append(
                f"set / network-instance default protocols bgp autonomous-system {local_as}"
            )
        if router_id:
            lines.append(
                f"set / network-instance default protocols bgp router-id {router_id}"
            )
        lines.append("set / network-instance default protocols bgp admin-state enable")
        # SRL requires at least one address-family to be enabled; IPv4 unicast is the default.
        lines.append("set / network-instance default protocols bgp afi-safi ipv4-unicast admin-state enable")

        # SRL requires neighbors to belong to a peer-group. Create one group per peer-as.
        peer_as_to_group: dict[str, str] = {}
        for nbr in node_nbrs:
            if nbr.peer_as not in peer_as_to_group:
                group_name = f"ebgp-{nbr.peer_as}"
                peer_as_to_group[nbr.peer_as] = group_name
                lines.append(
                    f"set / network-instance default protocols bgp group {group_name} "
                    f"peer-as {nbr.peer_as}"
                )
                lines.append(
                    f"set / network-instance default protocols bgp group {group_name} "
                    f"admin-state enable"
                )

        for nbr in node_nbrs:
            peer_ip = nbr.peer_ip
            peer_as = nbr.peer_as
            group_name = peer_as_to_group[peer_as]
            lines.append(
                f"set / network-instance default protocols bgp neighbor {peer_ip} "
                f"peer-group {group_name}"
            )
            lines.append(
                f"set / network-instance default protocols bgp neighbor {peer_ip} "
                f"admin-state enable"
            )
            local_ip_cidr = _infer_local_ip_for_peer(node_name, peer_ip, snapshot)
            if local_ip_cidr:
                local_ip = local_ip_cidr.split("/")[0]
                lines.append(
                    f"set / network-instance default protocols bgp neighbor {peer_ip} "
                    f"transport local-address {local_ip}"
                )

    # ── OSPF ──────────────────────────────────────────────────────────────
    ospf_nbrs = [n for n in snapshot.ospf_neighbors if n.device == node_name]
    if ospf_nbrs:
        lines.append("# --- OSPF ---")
        lines.append("set / network-instance default protocols ospf instance main admin-state enable")
        for nbr in ospf_nbrs:
            if nbr.interface:
                srl_iface = map_iface_to_srl(nbr.interface)
                lines.append(
                    f"set / network-instance default protocols ospf instance main "
                    f"area 0.0.0.0 interface {srl_iface}.0 interface-type point-to-point"
                )

    if not lines:
        return f"# no config derived for {node_name}\n"

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers — IP / AS / router-id inference from snapshot
# ---------------------------------------------------------------------------


def _infer_interface_ip(node: str, iface_name: str, snapshot: "ControlPlaneSnapshot") -> str | None:
    """Infer P2P interface IP with prefix for a node's interface.

    Strategy: for each connected /30 route, check if a BGP neighbor IP falls
    in that subnet. If so, the local IP is the other host address in the /30.

    Returns CIDR string (e.g. "10.99.0.1/30") or None.
    """
    peer_ips = [nbr.peer_ip for nbr in snapshot.bgp_neighbors if nbr.device == node]
    if not peer_ips:
        return None

    for route in snapshot.routes:
        if route.device != node:
            continue
        if route.protocol not in ("connected", "local", "direct"):
            continue
        try:
            net = ipaddress.ip_network(route.network, strict=False)
        except ValueError:
            continue
        if net.prefixlen != 30:
            continue

        for peer_ip in peer_ips:
            try:
                peer_addr = ipaddress.ip_address(peer_ip)
            except ValueError:
                continue
            if peer_addr in net:
                hosts = list(net.hosts())  # subnet+1, subnet+2
                for host in hosts:
                    if host != peer_addr:
                        return f"{host}/{net.prefixlen}"
    return None


def _infer_local_as(node: str, snapshot: "ControlPlaneSnapshot") -> str | None:
    """Infer local AS number for a node via cross-reference.

    Strategy: find BGP sessions from OTHER nodes that have peer_ip matching
    one of this node's known IPs (from connected /32 routes or router-id).
    Their peer_as is this node's local AS.
    """
    node_ips: set[str] = set()
    for route in snapshot.routes:
        if route.device != node:
            continue
        if route.protocol in ("connected", "local", "direct"):
            ip = route.network.split("/")[0]
            node_ips.add(ip)

    for nbr in snapshot.bgp_neighbors:
        if nbr.device != node and nbr.peer_ip in node_ips:
            return nbr.peer_as

    return None


def _infer_router_id(node: str, snapshot: "ControlPlaneSnapshot") -> str | None:
    """Infer BGP router-id for a node from connected routes or Loopback.

    Prefers /32s that are NOT inside a P2P /30 subnet (i.e. true loopbacks).
    Falls back to any connected /32 if no loopback is found.
    """
    # Collect all connected /30 networks to exclude their host addresses
    p2p_nets: list[ipaddress.IPv4Network] = []
    for route in snapshot.routes:
        if route.device != node or route.protocol not in ("connected", "local", "direct"):
            continue
        try:
            net = ipaddress.ip_network(route.network, strict=False)
            if net.prefixlen == 30:
                p2p_nets.append(net)
        except ValueError:
            pass

    fallback: str | None = None
    for route in snapshot.routes:
        if route.device != node:
            continue
        if "/32" not in route.network:
            continue
        if route.protocol not in ("connected", "local", "direct"):
            continue
        ip_str = route.network.split("/")[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if not any(addr in net for net in p2p_nets):
            return ip_str   # true loopback — use immediately
        if fallback is None:
            fallback = ip_str  # P2P host /32 — keep as fallback
    return fallback


def _infer_local_ip_for_peer(
    node: str,
    peer_ip: str,
    snapshot: "ControlPlaneSnapshot",
) -> str | None:
    """Return the local interface IP (with prefix) that reaches peer_ip.

    Searches connected /30 routes on node; returns the host address in the
    same subnet that is NOT peer_ip (i.e. our local address).
    """
    try:
        peer_addr = ipaddress.ip_address(peer_ip)
    except ValueError:
        return None

    for route in snapshot.routes:
        if route.device != node:
            continue
        if route.protocol not in ("connected", "local", "direct"):
            continue
        try:
            net = ipaddress.ip_network(route.network, strict=False)
        except ValueError:
            continue
        if net.prefixlen != 30:
            continue
        if peer_addr in net:
            for host in net.hosts():
                if host != peer_addr:
                    return f"{host}/{net.prefixlen}"
    return None

"""Sim-side deterministic prod-form CLI generators (R94.1).

Parallel to R89 / R90 (lab-side SRL generators) but for production-form
CLI on real Junos / IOS devices. Produces complete, deployable CLI —
no ellipses, no placeholders, no LLM. Same Type-B deterministic pattern
ADR-0007 enshrines: agent supplies intent + structured device facts,
helpers produce CLI.

Public API:
    * ``generate_junos_ebgp_config`` / ``generate_junos_ebgp_rollback``
    * ``generate_ios_ebgp_config``   / ``generate_ios_ebgp_rollback``
    * ``derive_prod_cli_from_tcf(tcf)`` — bulk helper that walks
      ``tcf.devices`` and dispatches per-platform / per-intent,
      returning ``(implementation, rollback)`` as JSON-serialisable
      ``list[dict]`` ready to feed back into ``tcf_emit_from_sim``.

Currently implemented: ``intent.type == "ebgp_direct"`` with platforms
``juniper_junos`` and ``cisco_ios``. Other intents / platforms raise
``ValueError`` so callers fail loud and either extend this module or
write CLI by hand.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from .tcf_schema import CabTcf


# Supported intent types — mirrors _R89_SUPPORTED_INTENTS shape so
# expanding both modules together is the natural upgrade path.
_PROD_SUPPORTED_INTENTS = {"ebgp_direct"}


# ---------------------------------------------------------------------------
# Junos generators
# ---------------------------------------------------------------------------


def generate_junos_ebgp_config(
    *,
    prod_intf: str,
    prod_intf_ip: str,           # e.g. "172.16.99.1/30"
    prod_loopback: str,          # e.g. "1.1.1.1"
    local_asn: int,
    neighbor_ip: str,            # e.g. "172.16.99.2"
    neighbor_loopback: str,      # e.g. "4.4.4.4" — used in export policy
    peer_asn: int,
    group_name: str,             # e.g. "ebgp-r4"
) -> list[str]:
    """Real, deployable Junos CLI for direct eBGP — no ellipses.

    Produces a self-contained set of ``set`` commands the operator can
    paste into Junos config mode. Includes:
      * physical interface IP
      * loopback IP + router-id + autonomous-system
      * BGP group + peer-as + neighbor + export-policy
      * policy-statement that exports own loopback only
    """
    return [
        f"set interfaces {prod_intf} unit 0 family inet address {prod_intf_ip}",
        f"set interfaces lo0 unit 0 family inet address {prod_loopback}/32",
        f"set routing-options router-id {prod_loopback}",
        f"set routing-options autonomous-system {local_asn}",
        f"set protocols bgp group {group_name} type external",
        f"set protocols bgp group {group_name} peer-as {peer_asn}",
        f"set protocols bgp group {group_name} local-address {prod_loopback}",
        f"set protocols bgp group {group_name} neighbor {neighbor_ip}",
        f"set protocols bgp group {group_name} export bgp-export",
        f"set policy-options policy-statement bgp-export term loopback "
        f"from route-filter {prod_loopback}/32 exact",
        f"set policy-options policy-statement bgp-export term loopback "
        f"then accept",
        f"set policy-options policy-statement bgp-export then reject",
    ]


def generate_junos_ebgp_rollback(
    *,
    prod_intf: str,
    group_name: str,
) -> list[str]:
    """Junos rollback for an ebgp_direct change.

    Conservative: only removes what we added (BGP group, export policy,
    interface unit). We deliberately do NOT delete the loopback IP or
    AS number — those are likely shared with other sessions. CAB
    approver must verify this assumption holds for the target device.
    """
    return [
        f"delete protocols bgp group {group_name}",
        "delete policy-options policy-statement bgp-export",
        f"delete interfaces {prod_intf} unit 0 family inet",
    ]


# ---------------------------------------------------------------------------
# Cisco IOS generators
# ---------------------------------------------------------------------------


def _ios_addr_mask(intf_ip_cidr: str) -> tuple[str, str]:
    """Convert ``172.16.99.2/30`` → ``("172.16.99.2", "255.255.255.252")``."""
    iface = ipaddress.IPv4Interface(intf_ip_cidr)
    return str(iface.ip), str(iface.netmask)


def generate_ios_ebgp_config(
    *,
    prod_intf: str,
    prod_intf_ip: str,           # CIDR form
    prod_loopback: str,
    local_asn: int,
    neighbor_ip: str,
    peer_asn: int,
) -> list[str]:
    """Real, deployable Cisco IOS CLI for direct eBGP — no ellipses."""
    addr, mask = _ios_addr_mask(prod_intf_ip)
    return [
        "interface Loopback0",
        f" ip address {prod_loopback} 255.255.255.255",
        f"interface {prod_intf}",
        f" ip address {addr} {mask}",
        " no shutdown",
        f"router bgp {local_asn}",
        f" bgp router-id {prod_loopback}",
        f" neighbor {neighbor_ip} remote-as {peer_asn}",
        f" neighbor {neighbor_ip} update-source Loopback0",
        " address-family ipv4",
        f"  network {prod_loopback} mask 255.255.255.255",
        f"  neighbor {neighbor_ip} activate",
        " exit-address-family",
    ]


def generate_ios_ebgp_rollback(
    *,
    local_asn: int,
    prod_intf: str,
) -> list[str]:
    """Cisco IOS rollback — drop the BGP process and the interface IP.

    Same conservative scope as the Junos rollback: doesn't touch the
    loopback or unrelated config.
    """
    return [
        f"no router bgp {local_asn}",
        f"interface {prod_intf}",
        " no ip address",
    ]


# ---------------------------------------------------------------------------
# Cross-vendor dispatch
# ---------------------------------------------------------------------------


def _other_device(devices: list[Any], self_name: str) -> Any:
    """Return the *other* device in a 2-node ebgp_direct change."""
    others = [d for d in devices if d.name != self_name]
    if len(others) != 1:
        raise ValueError(
            f"ebgp_direct expects exactly 2 devices; got "
            f"{[d.name for d in devices]}"
        )
    return others[0]


def _ebgp_subnet_assignments(lab_subnet: str, device_names: list[str]) -> dict[str, str]:
    """For a /30 subnet, assign first usable host to first device, second
    usable host to second device. Mirrors R89's address logic so prod
    and lab plans align by construction."""
    net = ipaddress.IPv4Network(lab_subnet, strict=False)
    hosts = list(net.hosts())
    if len(hosts) < 2:
        raise ValueError(
            f"ebgp_direct subnet {lab_subnet!r} too small — need at "
            f"least 2 host addresses, got {len(hosts)}"
        )
    if len(device_names) != 2:
        raise ValueError(
            f"ebgp_direct expects 2 devices; got {device_names}"
        )
    return {
        device_names[0]: f"{hosts[0]}/{net.prefixlen}",
        device_names[1]: f"{hosts[1]}/{net.prefixlen}",
    }


def derive_prod_cli_from_tcf(
    tcf: CabTcf,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate ``(implementation, rollback)`` blocks from a TCF.

    Returns two lists of plain dicts (CliBlock-shaped) so callers can
    drop them straight into ``tcf_emit_from_sim``'s
    ``implementation_json`` / ``rollback_json`` parameters.

    Raises ``ValueError`` when the intent or any device platform is
    unsupported — callers must extend this module or pass CLI by hand.
    """
    if tcf.intent.type not in _PROD_SUPPORTED_INTENTS:
        raise ValueError(
            f"prod-CLI generation for intent {tcf.intent.type!r} not "
            f"implemented. Supported: {sorted(_PROD_SUPPORTED_INTENTS)}. "
            f"Either extend olav.core.cab.prod_cli or pass "
            f"implementation_json explicitly."
        )

    lab_subnet = getattr(tcf.intent, "lab_subnet", None)
    if not lab_subnet:
        raise ValueError(
            "ebgp_direct intent requires 'lab_subnet' (a /30 between "
            "the two devices) — none on intent."
        )

    names = [d.name for d in tcf.devices]
    intf_ips = _ebgp_subnet_assignments(lab_subnet, names)

    impl: list[dict[str, Any]] = []
    rb: list[dict[str, Any]] = []

    for d in tcf.devices:
        peer = _other_device(tcf.devices, d.name)
        peer_ip_cidr = intf_ips[peer.name]
        peer_ip = peer_ip_cidr.split("/", 1)[0]
        own_ip_cidr = intf_ips[d.name]
        group_name = f"ebgp-{peer.name.lower()}"

        if d.platform == "juniper_junos":
            impl_cli = generate_junos_ebgp_config(
                prod_intf=d.prod_intf or "ge-0/0/0",
                prod_intf_ip=own_ip_cidr,
                prod_loopback=d.prod_loopback or "0.0.0.0",
                local_asn=int(d.prod_asn or 0),
                neighbor_ip=peer_ip,
                neighbor_loopback=peer.prod_loopback or "0.0.0.0",
                peer_asn=int(peer.prod_asn or 0),
                group_name=group_name,
            )
            rb_cli = generate_junos_ebgp_rollback(
                prod_intf=d.prod_intf or "ge-0/0/0",
                group_name=group_name,
            )
        elif d.platform == "cisco_ios":
            impl_cli = generate_ios_ebgp_config(
                prod_intf=d.prod_intf or "Ethernet0/0",
                prod_intf_ip=own_ip_cidr,
                prod_loopback=d.prod_loopback or "0.0.0.0",
                local_asn=int(d.prod_asn or 0),
                neighbor_ip=peer_ip,
                peer_asn=int(peer.prod_asn or 0),
            )
            rb_cli = generate_ios_ebgp_rollback(
                local_asn=int(d.prod_asn or 0),
                prod_intf=d.prod_intf or "Ethernet0/0",
            )
        else:
            raise ValueError(
                f"prod-CLI generation for platform {d.platform!r} on "
                f"device {d.name!r} not implemented. Supported: "
                f"juniper_junos, cisco_ios."
            )

        impl.append({
            "device": d.name,
            "phase": 1,
            "action": "configure",
            "cli": impl_cli,
        })
        rb.append({
            "device": d.name,
            "phase": "rb1",
            "action": "configure",
            "cli": rb_cli,
        })

    return impl, rb


__all__ = [
    "derive_prod_cli_from_tcf",
    "generate_ios_ebgp_config",
    "generate_ios_ebgp_rollback",
    "generate_junos_ebgp_config",
    "generate_junos_ebgp_rollback",
]

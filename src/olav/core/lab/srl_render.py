"""generate_srl_lab_config — R89 deterministic prod→SRL translator.

Takes a structured description of the change (devices + change_intent)
and emits SRL CLI configuration for each lab node, using the canonical
23-line per-node skeleton documented in
``shared:ops/srl_spec_generation_rules.expert.yaml``.

Replaces the LLM-driven prod→SRL translation step in ops-lab.  The
agent's job collapses to:

  1. read_file(prod_spec) — extract change intent + devices
  2. execute_sql netops DB — get true platform / loopback / asn
  3. generate_clab_topology(devices, lab_name)         (R88-A)
  4. generate_srl_lab_config(devices, change_intent)   (THIS TOOL)
  5. save_lab_config(node, srl_config[node])
  6. deploy_and_push_lab
  7. exec_on_node verify
  8. CAB report
  9. destroy_lab

Step 4 produces SRL CLI deterministically; the LLM never has to
reproduce 23 lines of YANG-correct syntax + IP/AS/group substitution
in free-form text.

Currently supports:
  - eBGP direct (single /30 link, two nodes, mutual peer-group)

Easy to extend (add new ``intent_type`` handlers):
  - eBGP via loopback (multihop)
  - iBGP route-reflector
  - OSPF point-to-point
  - Static routes

See ``dev_docs/00 § ISSUE-OPS-LAB-CANT-TRANSLATE-PROD-TO-SRL`` and
``dev_docs/64 § Type B`` for context.
"""

from __future__ import annotations

import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent
while _PROJECT_ROOT.parent != _PROJECT_ROOT and not (_PROJECT_ROOT / "pyproject.toml").exists():
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# Lab node naming + interface conventions (mirrors generate_clab_topology)
# ---------------------------------------------------------------------------


def _to_lab_name(prod_name: str) -> str:
    """Prod device name → lab node name (lowercase, CLAB convention)."""
    return prod_name.lower()


def _validate_lab_subnet(subnet: str) -> ipaddress.IPv4Network:
    """Validate that ``subnet`` is a usable /30 (or longer) for a 2-node link."""
    net = ipaddress.IPv4Network(subnet, strict=False)
    if net.prefixlen > 30:
        raise ValueError(
            f"lab_subnet {subnet!r}: prefix length {net.prefixlen} too long; "
            f"need /30 or shorter for a 2-node link"
        )
    if net.num_addresses < 4:
        raise ValueError(
            f"lab_subnet {subnet!r}: need at least 4 addresses (network + 2 hosts + broadcast)"
        )
    return net


# ---------------------------------------------------------------------------
# eBGP direct: per-node 23-line SRL skeleton
# ---------------------------------------------------------------------------


def _render_ebgp_direct_node(
    *,
    lab_node: str,
    lab_iface: str,
    lab_link_ip: str,        # "172.16.99.1/30"
    loopback: str,           # "1.1.1.1/32" or "1.1.1.1"
    local_as: int,
    peer_lab_node: str,      # "r4"
    peer_link_ip: str,       # "172.16.99.2" (no /30 — SRL neighbor is bare host)
    peer_as: int,
) -> str:
    """Emit the 23-line SRL CLI for one node in an eBGP-direct lab.

    Mirrors the exact ordering in
    ``shared:ops/srl_spec_generation_rules.expert.yaml``.  Lines are
    intentionally kept in the order SRL needs (interface → subinterface →
    network-instance binding → policy → BGP) so a strict-mode commit
    accepts them on the first try.
    """
    # Normalize loopback to host (no /32) and to /32 for prefix-set
    lo_host = loopback.split("/")[0] if "/" in loopback else loopback
    lo_with_mask = f"{lo_host}/32"

    # Group name: per-peer convention so r1 has group ebgp-r4 and vice-versa
    group = f"ebgp-{peer_lab_node}"

    lines = [
        # Interface
        f"set / interface {lab_iface} admin-state enable",
        f"set / interface {lab_iface} subinterface 0 admin-state enable",
        f"set / interface {lab_iface} subinterface 0 ipv4 admin-state enable",
        f"set / interface {lab_iface} subinterface 0 ipv4 address {lab_link_ip}",
        # Loopback (system0)
        f"set / interface system0 admin-state enable",
        f"set / interface system0 subinterface 0 admin-state enable",
        f"set / interface system0 subinterface 0 ipv4 admin-state enable",
        f"set / interface system0 subinterface 0 ipv4 address {lo_with_mask}",
        # Network-instance binding
        f"set / network-instance default interface {lab_iface}.0",
        f"set / network-instance default interface system0.0",
        # Routing policy (so eBGP exports the loopback)
        f"set / routing-policy prefix-set loopbacks prefix {lo_with_mask} mask-length-range exact",
        f"set / routing-policy policy export-bgp statement 10 match prefix-set loopbacks",
        f"set / routing-policy policy export-bgp statement 10 action policy-result accept",
        f"set / routing-policy policy export-bgp default-action policy-result reject",
        # BGP
        f"set / network-instance default protocols bgp admin-state enable",
        f"set / network-instance default protocols bgp autonomous-system {local_as}",
        f"set / network-instance default protocols bgp router-id {lo_host}",
        f"set / network-instance default protocols bgp afi-safi ipv4-unicast admin-state enable",
        f"set / network-instance default protocols bgp ebgp-default-policy import-reject-all false",
        f"set / network-instance default protocols bgp group {group} peer-as {peer_as}",
        f"set / network-instance default protocols bgp group {group} export-policy [ export-bgp ]",
        f"set / network-instance default protocols bgp neighbor {peer_link_ip} peer-group {group}",
    ]
    return "\n".join(lines) + "\n"


def _generate_ebgp_direct(
    devices: list[dict],
    change_intent: dict,
    warnings: list[str],
) -> dict[str, str]:
    """Emit per-node SRL CLI for eBGP direct between two devices.

    Expected:
      devices = [
        {"name": "R1", "loopback": "1.1.1.1/32", "asn": 65000},
        {"name": "R4", "loopback": "4.4.4.4/32", "asn": 65001},
      ]
      change_intent = {"type": "ebgp_direct", "lab_subnet": "172.16.99.0/30"}
    """
    if len(devices) != 2:
        raise ValueError(
            f"ebgp_direct requires exactly 2 devices; got {len(devices)}"
        )

    # Validate + allocate /30
    subnet = change_intent.get("lab_subnet", "172.16.99.0/30")
    net = _validate_lab_subnet(subnet)
    hosts = list(net.hosts())  # for /30 → [.1, .2]
    if len(hosts) < 2:
        raise ValueError(
            f"lab_subnet {subnet!r} must yield ≥ 2 host addresses; got {len(hosts)}"
        )

    a, b = devices[0], devices[1]
    a_lab = _to_lab_name(a["name"])
    b_lab = _to_lab_name(b["name"])

    a_link_ip = f"{hosts[0]}/{net.prefixlen}"
    b_link_ip = f"{hosts[1]}/{net.prefixlen}"
    a_link_host = str(hosts[0])
    b_link_host = str(hosts[1])

    # Lab interface — convention: e1-1 for the single link
    lab_iface = "ethernet-1/1"

    a_config = _render_ebgp_direct_node(
        lab_node=a_lab,
        lab_iface=lab_iface,
        lab_link_ip=a_link_ip,
        loopback=a["loopback"],
        local_as=int(a["asn"]),
        peer_lab_node=b_lab,
        peer_link_ip=b_link_host,
        peer_as=int(b["asn"]),
    )
    b_config = _render_ebgp_direct_node(
        lab_node=b_lab,
        lab_iface=lab_iface,
        lab_link_ip=b_link_ip,
        loopback=b["loopback"],
        local_as=int(b["asn"]),
        peer_lab_node=a_lab,
        peer_link_ip=a_link_host,
        peer_as=int(a["asn"]),
    )
    return {a_lab: a_config, b_lab: b_config}


# ---------------------------------------------------------------------------
# Tool entry point
# ---------------------------------------------------------------------------


_SUPPORTED_INTENTS = {"ebgp_direct"}




def generate_srl_lab_config(
    nodes: list[str],
    loopbacks: list[str],
    asns: list[int],
    intent_type: str = "ebgp_direct",
    lab_subnet: str = "172.16.99.0/30",
) -> str:
    """Generate SRL CLI configs for each lab node, deterministic.

    Use this BEFORE ``save_lab_config`` when validating a prod CAB
    spec in an SRL digital twin.  Replaces the LLM-driven prod→SRL
    translation with a deterministic 22-line per-node template render
    — the agent doesn't have to reproduce SRL YANG syntax in
    free-form text (unreliable for small models).

    Schema is **3 parallel arrays** (small models handle this much
    better than ``list[dict]``):

        nodes      = ["R1", "R4"]       # prod device names
        loopbacks  = ["1.1.1.1", "4.4.4.4"]   # bare host or "/32"
        asns       = [65000, 65001]     # local AS per node, same order

    Args:
        nodes: Prod device names. Lab nodes are auto-lowercased
            (R1 → r1) to match CLAB convention. ``len(nodes)`` must
            match the intent (2 for ``ebgp_direct``).
        loopbacks: Loopback IPs in the same order as ``nodes``. Each
            may be bare (``"1.1.1.1"``) or with mask (``"1.1.1.1/32"``);
            tool normalises to /32. Used as the SRL ``router-id`` and
            ``system0`` IP for that node.
        asns: Local AS numbers in the same order as ``nodes``. For
            eBGP intents these must differ (different AS per node).
        intent_type: Which SRL template to render. Currently only
            ``ebgp_direct`` (2 nodes, single /30 link, mutual eBGP)
            is supported.
        lab_subnet: /30 (or shorter) to allocate for the lab link.
            Default ``172.16.99.0/30``. Hosts are assigned in
            ``nodes`` order: ``nodes[0]`` gets the first host, etc.

    Returns:
        JSON string with ``configs`` (dict mapping lab node → SRL CLI
        block of 22 lines), ``warnings`` (list of strings), and
        ``intent_type`` (echo of the intent used). Pass
        ``configs[lab_node].splitlines()`` to ``save_lab_config`` for
        each node.

    Example:
        >>> result = generate_srl_lab_config(
        ...     nodes=["R1", "R4"],
        ...     loopbacks=["1.1.1.1", "4.4.4.4"],
        ...     asns=[65000, 65001],
        ... )
        >>> data = json.loads(result)
        >>> save_lab_config(node="r1", config_lines=data["configs"]["r1"].splitlines())
        >>> save_lab_config(node="r4", config_lines=data["configs"]["r4"].splitlines())
    """
    warnings: list[str] = []

    if not isinstance(nodes, list) or not nodes:
        return json.dumps({
            "status": "error",
            "error": "nodes must be a non-empty list of device names",
        })
    if not isinstance(loopbacks, list) or len(loopbacks) != len(nodes):
        return json.dumps({
            "status": "error",
            "error": (
                f"loopbacks must be a list of the same length as nodes "
                f"(got {len(loopbacks) if isinstance(loopbacks, list) else type(loopbacks).__name__} "
                f"vs {len(nodes)} nodes)"
            ),
        })
    if not isinstance(asns, list) or len(asns) != len(nodes):
        return json.dumps({
            "status": "error",
            "error": (
                f"asns must be a list of the same length as nodes "
                f"(got {len(asns) if isinstance(asns, list) else type(asns).__name__} "
                f"vs {len(nodes)} nodes)"
            ),
        })

    if intent_type not in _SUPPORTED_INTENTS:
        return json.dumps({
            "status": "error",
            "error": (
                f"unsupported intent type {intent_type!r}; "
                f"supported: {sorted(_SUPPORTED_INTENTS)}"
            ),
        })

    # Build the structured devices list internally
    try:
        effective_devices = [
            {"name": n, "loopback": str(lb), "asn": int(a)}
            for n, lb, a in zip(nodes, loopbacks, asns, strict=True)
        ]
    except (TypeError, ValueError) as e:
        return json.dumps({
            "status": "error",
            "error": f"failed to zip nodes/loopbacks/asns: {e}",
        })

    effective_intent = {"type": intent_type, "lab_subnet": lab_subnet}

    try:
        if intent_type == "ebgp_direct":
            configs = _generate_ebgp_direct(effective_devices, effective_intent, warnings)
        else:
            return json.dumps({
                "status": "error",
                "error": f"no handler for intent {intent_type!r}",
            })
    except (ValueError, KeyError, TypeError) as e:
        return json.dumps({
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
        })

    # Fix #4 (2026-05-07): downstream consumers (save_lab_config,
    # deploy_and_push_lab) expect dict[str, list[str]] per the
    # public API.  _render_*_node functions return a single
    # newline-joined str, which iterates char-by-char when fed to
    # ``"\n".join(str(l) for l in config_lines)`` in
    # deploy_and_push.py:246 — producing a script whose line 2 is
    # the bare char "s" (first char of "set"), which SRL YANG
    # parser correctly rejects.  Split before returning so the
    # contract matches the docstring + caller expectations.
    configs_as_lines: dict[str, list[str]] = {
        node: cfg.splitlines() if isinstance(cfg, str) else list(cfg)
        for node, cfg in configs.items()
    }

    return json.dumps({
        "status": "ok",
        "intent_type": intent_type,
        "configs": configs_as_lines,
        "warnings": warnings,
    })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    args = json.loads(parsed.args_json)
    print(generate_srl_lab_config.invoke(args))

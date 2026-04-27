"""generate_srl_rollback_config — R90 Phase 6 rollback generator.

Deterministic Type B counterpart to ``generate_srl_lab_config`` (R89).
Produces SRL ``delete /`` CLI that undoes what R89's ``set /`` CLI
applied, returning the lab to a clean state ready for re-application
or destroy.

Same signature shape as R89 (3 parallel arrays + intent_type +
lab_subnet) so the lab agent can call it identically. Same Type B
guarantees: deterministic output, no LLM synthesis, fixed schema.

Flow:
  R89  set /   apply  → lab BGP established, routes exchanged
  R90  delete / undo  → lab BGP gone, no residual config
  agent verifies reversion via exec_on_node:
    - show network-instance default protocols bgp neighbor → empty
    - show interface ethernet-1/N → no IPv4 address
"""

from __future__ import annotations

import ipaddress
import json
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
while _PROJECT_ROOT.parent != _PROJECT_ROOT and not (_PROJECT_ROOT / "pyproject.toml").exists():
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


_SUPPORTED_INTENTS = {"ebgp_direct"}


def _to_lab_name(prod_name: str) -> str:
    return prod_name.lower()


def _validate_lab_subnet(subnet: str) -> ipaddress.IPv4Network:
    net = ipaddress.IPv4Network(subnet, strict=False)
    if net.prefixlen > 30:
        raise ValueError(
            f"lab_subnet {subnet!r}: prefix length {net.prefixlen} too long"
        )
    return net


def _render_ebgp_direct_rollback(*, lab_iface: str) -> str:
    """7-line per-node SRL rollback for ebgp_direct.

    Order matters: tear down higher-level constructs (BGP, routing
    policy, NI bindings) before deleting subinterfaces, so the SRL
    YANG dependency graph stays satisfied throughout the commit.

    Also a single ``delete / network-instance default protocols bgp``
    wipes the entire BGP config for the default NI in one go — we
    don't have to enumerate per-group/per-neighbor deletes.
    """
    lines = [
        # Wipe BGP protocol entirely (covers groups, neighbors, afi-safi,
        # asn, router-id, ebgp-default-policy)
        f"delete / network-instance default protocols bgp",
        # Tear down routing policy that referenced the loopback prefix-set
        f"delete / routing-policy policy export-bgp",
        f"delete / routing-policy prefix-set loopbacks",
        # Unbind subinterfaces from the network-instance
        f"delete / network-instance default interface {lab_iface}.0",
        f"delete / network-instance default interface system0.0",
        # Drop IPv4 addresses + admin-state on the subinterfaces.
        # We delete the whole subinterface 0 — that's everything we set.
        # NOTE: physical interface (ethernet-1/N) and system0 themselves
        # are NOT deleted (they're SRL-default resources that always
        # exist on a container; we only un-do our config).
        f"delete / interface {lab_iface} subinterface 0",
        f"delete / interface system0 subinterface 0",
    ]
    return "\n".join(lines) + "\n"


def _generate_ebgp_direct(devices: list[dict]) -> dict[str, str]:
    if len(devices) != 2:
        raise ValueError(
            f"ebgp_direct rollback requires exactly 2 devices; got {len(devices)}"
        )
    # Lab interface is e1-1 by R89 convention (sequential per-node
    # starting at 1; both endpoints land on ethernet-1/1)
    lab_iface = "ethernet-1/1"

    out: dict[str, str] = {}
    for d in devices:
        out[_to_lab_name(d["name"])] = _render_ebgp_direct_rollback(
            lab_iface=lab_iface,
        )
    return out


from langchain_core.tools import tool


@tool
def generate_srl_rollback_config(
    nodes: list[str],
    loopbacks: list[str],
    asns: list[int],
    intent_type: str = "ebgp_direct",
    lab_subnet: str = "172.16.99.0/30",
) -> str:
    """Generate SRL CLI ``delete /`` commands to undo R89's apply.

    Use this for **rollback validation** — after a successful apply
    + post_check pass, push the rollback CLI and verify the lab
    returns to a clean state (BGP neighbor table empty, no IP on
    e1-1 subinterface, etc.). A change plan whose rollback can't
    cleanly revert is a CAB BLOCKER.

    Schema is identical to ``generate_srl_lab_config`` so the agent
    can pass the SAME args (often pulled from
    ``tcf_to_r89_args(tcf)``).

    Args:
        nodes: Prod device names. Lab nodes auto-lowercased
            (R1 → r1) to match CLAB convention.
        loopbacks: Per-device loopback IPs (kept for signature
            compatibility with R89; not actually used in the
            rollback render since ``delete / interface system0
            subinterface 0`` removes the IP regardless of value).
        asns: Per-device local AS numbers (kept for signature
            compat; ``delete / network-instance default protocols
            bgp`` covers all ASN/group/neighbor state).
        intent_type: Currently only ``"ebgp_direct"`` supported.
        lab_subnet: Kept for signature compat; rollback doesn't
            reference subnet directly.

    Returns:
        JSON envelope:
          status: "ok" / "error"
          intent_type: echo
          configs: dict mapping lab_node → SRL CLI block (7 lines
            per node)
          warnings: list[str]

    Example:
        >>> result = generate_srl_rollback_config(
        ...     nodes=["R1", "R4"],
        ...     loopbacks=["1.1.1.1", "4.4.4.4"],
        ...     asns=[65000, 65001],
        ... )
        >>> data = json.loads(result)
        >>> push_node_config(node="r1", config=data["configs"]["r1"])
        >>> push_node_config(node="r4", config=data["configs"]["r4"])
        >>> # Verify reversion via exec_on_node
    """
    warnings: list[str] = []

    if not isinstance(nodes, list) or not nodes:
        return json.dumps({
            "status": "error",
            "error": "nodes must be a non-empty list",
        })
    if not isinstance(loopbacks, list) or len(loopbacks) != len(nodes):
        return json.dumps({
            "status": "error",
            "error": (
                f"loopbacks length must match nodes "
                f"({len(loopbacks) if isinstance(loopbacks, list) else type(loopbacks).__name__} vs {len(nodes)})"
            ),
        })
    if not isinstance(asns, list) or len(asns) != len(nodes):
        return json.dumps({
            "status": "error",
            "error": (
                f"asns length must match nodes "
                f"({len(asns) if isinstance(asns, list) else type(asns).__name__} vs {len(nodes)})"
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

    # lab_subnet validation — same shape rule as R89 even though
    # rollback doesn't use it (catches obvious calls with /32 etc.)
    try:
        _validate_lab_subnet(lab_subnet)
    except ValueError as e:
        return json.dumps({
            "status": "error",
            "error": f"lab_subnet invalid: {e}",
        })

    devices = [
        {"name": n, "loopback": str(lb), "asn": int(a)}
        for n, lb, a in zip(nodes, loopbacks, asns, strict=True)
    ]

    try:
        if intent_type == "ebgp_direct":
            configs = _generate_ebgp_direct(devices)
        else:
            return json.dumps({
                "status": "error",
                "error": f"no rollback handler for intent {intent_type!r}",
            })
    except (ValueError, KeyError, TypeError) as e:
        return json.dumps({
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
        })

    return json.dumps({
        "status": "ok",
        "intent_type": intent_type,
        "configs": configs,
        "warnings": warnings,
    })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    args = json.loads(parsed.args_json)
    print(generate_srl_rollback_config.invoke(args))

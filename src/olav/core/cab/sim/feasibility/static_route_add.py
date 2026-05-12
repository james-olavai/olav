"""static_route_add feasibility rule.

Refuses when:
  * scope length ≠ 1                            → wrong_device_count
  * scoped device missing in facts              → missing_facts
  * intent_args lacks dst_prefix or next_hop_ip → missing_args
  * dst_prefix not a valid CIDR                 → invalid_cidr
  * next_hop_ip not a valid IPv4                → invalid_next_hop
  * admin_distance outside 1..255               → invalid_admin_distance
"""
from __future__ import annotations

import ipaddress
from typing import Any

from olav.core.cab.schemas import Blocker, DraftChangePlan, FeasibilityVerdict

from ._common import device_index, missing_facts_blocker


def _required_args_missing(args: dict[str, Any]) -> list[str]:
    return [k for k in ("dst_prefix", "next_hop_ip") if not args.get(k)]


def check(draft: DraftChangePlan) -> FeasibilityVerdict:
    blockers: list[Blocker] = []

    scope = draft.devices_in_scope
    if len(scope) != 1:
        blockers.append(Blocker(
            code="wrong_device_count",
            message=f"static_route_add applies to exactly 1 device; got {len(scope)}",
            evidence={"devices_in_scope": scope},
        ))
        return FeasibilityVerdict(
            chosen_intent="static_route_add",
            feasibility="BLOCKED",
            blockers=blockers,
        )

    idx = device_index(draft.facts_collected)
    if (m := missing_facts_blocker(scope, idx)):
        blockers.append(m)

    args = draft.intent_args
    if (missing := _required_args_missing(args)):
        blockers.append(Blocker(
            code="missing_args",
            message=(
                f"static_route_add requires {missing} in intent_args; "
                f"only got {sorted(args.keys())}"
            ),
            evidence={"missing": missing, "given": sorted(args.keys())},
        ))
    else:
        try:
            ipaddress.ip_network(args["dst_prefix"], strict=False)
        except (ValueError, TypeError) as e:
            blockers.append(Blocker(
                code="invalid_cidr",
                message=f"dst_prefix {args['dst_prefix']!r} is not a valid CIDR: {e}",
                evidence={"dst_prefix": args["dst_prefix"]},
            ))
        try:
            ipaddress.IPv4Address(args["next_hop_ip"])
        except (ValueError, TypeError) as e:
            blockers.append(Blocker(
                code="invalid_next_hop",
                message=f"next_hop_ip {args['next_hop_ip']!r} is not a valid IPv4: {e}",
                evidence={"next_hop_ip": args["next_hop_ip"]},
            ))

    ad = args.get("admin_distance", 1)
    if ad is not None and not (isinstance(ad, int) and 1 <= ad <= 255):
        blockers.append(Blocker(
            code="invalid_admin_distance",
            message=f"admin_distance must be an int in 1..255; got {ad!r}",
            evidence={"admin_distance": ad},
        ))

    return FeasibilityVerdict(
        chosen_intent="static_route_add",
        feasibility="BLOCKED" if blockers else "OK",
        blockers=blockers,
    )

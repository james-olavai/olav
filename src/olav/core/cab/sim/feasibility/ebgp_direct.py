"""ebgp_direct feasibility rule.

Refuses when:
  * scope length ≠ 2                 → wrong_device_count
  * a scoped device missing in facts → missing_facts
  * either device.local_as is None   → missing_local_as
  * ASNs match                       → same_asn       (+suggest ibgp_direct)
  * no direct L2 edge between them   → not_directly_connected (+suggest ibgp_direct)
"""
from __future__ import annotations

from olav.core.cab.schemas import (
    Blocker,
    DraftChangePlan,
    FeasibilityVerdict,
    SuggestedAlternative,
)

from ._common import device_index, edge_pairs, missing_facts_blocker


def check(draft: DraftChangePlan) -> FeasibilityVerdict:
    blockers: list[Blocker] = []
    alternatives: list[SuggestedAlternative] = []

    scope = draft.devices_in_scope
    if len(scope) != 2:
        blockers.append(Blocker(
            code="wrong_device_count",
            message=f"ebgp_direct requires exactly 2 devices; got {len(scope)}",
            evidence={"devices_in_scope": scope},
        ))
        return FeasibilityVerdict(
            chosen_intent="ebgp_direct",
            feasibility="BLOCKED",
            blockers=blockers,
        )

    idx = device_index(draft.facts_collected)
    if (m := missing_facts_blocker(scope, idx)):
        blockers.append(m)
        return FeasibilityVerdict(
            chosen_intent="ebgp_direct",
            feasibility="BLOCKED",
            blockers=blockers,
        )

    a, b = scope
    fa, fb = idx[a], idx[b]

    if fa.local_as is None or fb.local_as is None:
        blockers.append(Blocker(
            code="missing_local_as",
            message=(
                f"local_as unknown for "
                f"{a if fa.local_as is None else b} — inspect_devices "
                f"did not return an ASN."
            ),
            evidence={
                f"{a}.local_as": fa.local_as,
                f"{b}.local_as": fb.local_as,
            },
        ))
    elif fa.local_as == fb.local_as:
        blockers.append(Blocker(
            code="same_asn",
            message=(
                f"{a} and {b} both in AS {fa.local_as}. eBGP requires "
                f"different ASNs."
            ),
            evidence={
                f"{a}.local_as": fa.local_as,
                f"{b}.local_as": fb.local_as,
            },
        ))
        alternatives.append(SuggestedAlternative(
            intent="ibgp_direct",
            rationale=(
                f"Both devices share AS {fa.local_as} — iBGP is the right "
                f"protocol when peers are in the same autonomous system."
            ),
            required_changes={"swap_intent_to": "ibgp_direct"},
        ))

    if frozenset({a, b}) not in edge_pairs(draft.facts_collected):
        blockers.append(Blocker(
            code="not_directly_connected",
            message=(
                f"{a} and {b} have no direct L2 link in facts.topology_edges. "
                f"ebgp_direct peers on interface IPs, which requires direct "
                f"L2 adjacency."
            ),
            evidence={
                "topology_edges_count": len(draft.facts_collected.topology_edges),
                "scope_pair": [a, b],
            },
        ))
        alternatives.append(SuggestedAlternative(
            intent="ibgp_direct",
            rationale=(
                f"iBGP can peer via loopbacks over IGP without requiring a "
                f"direct L2 link between {a} and {b}."
            ),
            required_changes={"swap_intent_to": "ibgp_direct"},
        ))

    return FeasibilityVerdict(
        chosen_intent="ebgp_direct",
        feasibility="BLOCKED" if blockers else "OK",
        blockers=blockers,
        suggested_alternatives=alternatives,
    )

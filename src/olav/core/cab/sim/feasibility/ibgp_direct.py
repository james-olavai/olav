"""ibgp_direct feasibility rule.

Refuses when:
  * scope length ≠ 2                 → wrong_device_count
  * a scoped device missing in facts → missing_facts
  * either device.local_as is None   → missing_local_as
  * ASNs differ                      → different_asn (+suggest ebgp_direct)
  * either device.loopback is None   → missing_loopback
"""
from __future__ import annotations

from olav.core.cab.schemas import (
    Blocker,
    DraftChangePlan,
    FeasibilityVerdict,
    SuggestedAlternative,
)

from ._common import device_index, missing_facts_blocker


def check(draft: DraftChangePlan) -> FeasibilityVerdict:
    blockers: list[Blocker] = []
    alternatives: list[SuggestedAlternative] = []

    scope = draft.devices_in_scope
    if len(scope) != 2:
        blockers.append(Blocker(
            code="wrong_device_count",
            message=f"ibgp_direct requires exactly 2 devices; got {len(scope)}",
            evidence={"devices_in_scope": scope},
        ))
        return FeasibilityVerdict(
            chosen_intent="ibgp_direct",
            feasibility="BLOCKED",
            blockers=blockers,
        )

    idx = device_index(draft.facts_collected)
    if (m := missing_facts_blocker(scope, idx)):
        blockers.append(m)
        return FeasibilityVerdict(
            chosen_intent="ibgp_direct",
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
                f"{a if fa.local_as is None else b}."
            ),
            evidence={
                f"{a}.local_as": fa.local_as,
                f"{b}.local_as": fb.local_as,
            },
        ))
    elif fa.local_as != fb.local_as:
        blockers.append(Blocker(
            code="different_asn",
            message=(
                f"{a} in AS {fa.local_as} != {b} in AS {fb.local_as}. "
                f"iBGP requires both peers in the same autonomous system."
            ),
            evidence={
                f"{a}.local_as": fa.local_as,
                f"{b}.local_as": fb.local_as,
            },
        ))
        alternatives.append(SuggestedAlternative(
            intent="ebgp_direct",
            rationale=(
                f"ASNs differ ({fa.local_as} vs {fb.local_as}) — eBGP is "
                f"the right protocol when peers are in different ASes."
            ),
            required_changes={"swap_intent_to": "ebgp_direct"},
        ))

    if fa.loopback is None or fb.loopback is None:
        blockers.append(Blocker(
            code="missing_loopback",
            message=(
                f"loopback unknown for "
                f"{a if fa.loopback is None else b}. iBGP peers on loopback "
                f"addresses so both devices must have one."
            ),
            evidence={
                f"{a}.loopback": fa.loopback,
                f"{b}.loopback": fb.loopback,
            },
        ))

    return FeasibilityVerdict(
        chosen_intent="ibgp_direct",
        feasibility="BLOCKED" if blockers else "OK",
        blockers=blockers,
        suggested_alternatives=alternatives,
    )

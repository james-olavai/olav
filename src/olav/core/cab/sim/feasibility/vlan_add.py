"""vlan_add feasibility rule.

Refuses when:
  * scope is empty                             → no_devices
  * scoped device missing in facts             → missing_facts
  * intent_args lacks vlan_id                  → missing_args
  * vlan_id outside 1..4094                    → invalid_vlan_id
"""
from __future__ import annotations

from olav.core.cab.schemas import Blocker, DraftChangePlan, FeasibilityVerdict

from ._common import device_index, missing_facts_blocker


def check(draft: DraftChangePlan) -> FeasibilityVerdict:
    blockers: list[Blocker] = []

    scope = draft.devices_in_scope
    if not scope:
        # Pydantic already enforces min_length=1, but keep a safety
        # check in case the rule is invoked outside the schema path.
        blockers.append(Blocker(
            code="no_devices",
            message="vlan_add requires at least one device in scope",
            evidence={"devices_in_scope": scope},
        ))
        return FeasibilityVerdict(
            chosen_intent="vlan_add",
            feasibility="BLOCKED",
            blockers=blockers,
        )

    idx = device_index(draft.facts_collected)
    if (m := missing_facts_blocker(scope, idx)):
        blockers.append(m)

    args = draft.intent_args
    vlan_id = args.get("vlan_id")
    if vlan_id is None:
        blockers.append(Blocker(
            code="missing_args",
            message="vlan_add requires vlan_id in intent_args",
            evidence={"given": sorted(args.keys())},
        ))
    elif not (isinstance(vlan_id, int) and 1 <= vlan_id <= 4094):
        blockers.append(Blocker(
            code="invalid_vlan_id",
            message=f"vlan_id must be an int in 1..4094; got {vlan_id!r}",
            evidence={"vlan_id": vlan_id},
        ))

    return FeasibilityVerdict(
        chosen_intent="vlan_add",
        feasibility="BLOCKED" if blockers else "OK",
        blockers=blockers,
    )

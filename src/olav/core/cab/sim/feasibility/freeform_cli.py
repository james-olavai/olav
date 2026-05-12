"""freeform_cli feasibility rule.

Wraps ``validate_prod_cli_completeness`` (the existing F.2 lint, will
relocate to sim/render/freeform.py on Day 6) and enforces the three
operational requirements that ISSUE-CAB-PROD-CLI-INCOMPLETE pinned
down: every scoped device needs CLI lines, a rollback, and at least
one post_check.

Refuses when:
  * scope is empty                                  → no_devices
  * a scoped device is missing from facts           → missing_facts
  * cli_per_device is empty or missing a scope dev  → missing_cli
  * rollback_per_device is empty or missing a dev   → missing_rollback
  * post_checks is empty                            → missing_post_checks
  * (Day 6) prod-CLI completeness lint hard-fails   → cli_completeness_failed
    (currently warnings only — kept as advisory)
"""
from __future__ import annotations

from typing import Any

from olav.core.cab.schemas import Blocker, DraftChangePlan, FeasibilityVerdict

from ._common import device_index, missing_facts_blocker


def _dict_missing_devices(d: dict[str, Any], scope: list[str]) -> list[str]:
    if not isinstance(d, dict):
        return list(scope)
    return [dev for dev in scope if not d.get(dev)]


def check(draft: DraftChangePlan) -> FeasibilityVerdict:
    blockers: list[Blocker] = []

    scope = draft.devices_in_scope
    if not scope:
        blockers.append(Blocker(
            code="no_devices",
            message="freeform_cli requires at least one device in scope",
            evidence={"devices_in_scope": scope},
        ))
        return FeasibilityVerdict(
            chosen_intent="freeform_cli",
            feasibility="BLOCKED",
            blockers=blockers,
        )

    idx = device_index(draft.facts_collected)
    if (m := missing_facts_blocker(scope, idx)):
        blockers.append(m)

    args = draft.intent_args
    cli = args.get("cli_per_device") or {}
    rollback = args.get("rollback_per_device") or {}
    post_checks = args.get("post_checks") or []

    if (cli_missing := _dict_missing_devices(cli, scope)):
        blockers.append(Blocker(
            code="missing_cli",
            message=(
                f"cli_per_device missing CLI lines for devices "
                f"{cli_missing}. Every device in scope must have at least "
                f"one CLI line."
            ),
            evidence={"missing": cli_missing, "scope": scope},
        ))

    if (rb_missing := _dict_missing_devices(rollback, scope)):
        blockers.append(Blocker(
            code="missing_rollback",
            message=(
                f"rollback_per_device missing for devices {rb_missing}. "
                f"Every change must have a rollback path."
            ),
            evidence={"missing": rb_missing, "scope": scope},
        ))

    if not post_checks:
        blockers.append(Blocker(
            code="missing_post_checks",
            message=(
                "post_checks is empty. TVT needs at least one post_check "
                "to verify the change took effect."
            ),
            evidence={"post_checks_count": 0},
        ))
    else:
        # Per-entry shape check — every post_check must name a `device`
        # that's in scope. Found in-vivo (2026-05-12): without this,
        # malformed entries pass feasibility and only blow up at the
        # render stage with a generic `render_failed: post_checks did
        # not match any provided device` message that's hard for an
        # LLM to recover from. Catch it here with a specific code so
        # the analyzer's revision retry has actionable info.
        scope_set = set(scope)
        bad = []
        for i, pc in enumerate(post_checks):
            if not isinstance(pc, dict):
                bad.append({"index": i, "reason": "not a dict", "value": repr(pc)})
                continue
            dev = pc.get("device")
            if not dev:
                bad.append({"index": i, "reason": "missing 'device' field",
                            "keys": sorted(pc.keys())})
            elif dev not in scope_set:
                bad.append({"index": i, "reason": "device not in scope",
                            "device": dev, "scope": list(scope_set)})
        if bad:
            blockers.append(Blocker(
                code="post_check_shape",
                message=(
                    f"post_checks has {len(bad)} malformed entries. "
                    f"Every post_check must be a dict with at least "
                    f"`device` (in devices_in_scope) + `command` + "
                    f"`expected_pattern` + `description`."
                ),
                evidence={"bad_entries": bad,
                          "expected_shape": {
                              "device": "<one of devices_in_scope>",
                              "command": "<show command>",
                              "expected_pattern": "<substring to match>",
                              "description": "<purpose>"}},
            ))

    return FeasibilityVerdict(
        chosen_intent="freeform_cli",
        feasibility="BLOCKED" if blockers else "OK",
        blockers=blockers,
    )

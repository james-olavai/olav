"""Structural + semantic lint for DraftChangePlan envelopes.

Runs AFTER Pydantic accepts the args (types + required fields OK)
and BEFORE writing draft.yaml. Catches the failure modes that
Pydantic can't:
  * field-name synonyms (e.g. ``expected`` instead of ``expected_pattern``)
  * empty string in semantically required slots (causes false-positive PASS)
  * facts_collected gaps (multi-device draft with empty topology_edges)
  * per-intent shape mismatches (e.g. freeform_cli cli_per_device missing a device)

Each LintError carries:
  * code         — stable, machine-readable
  * message      — human-readable
  * field        — JSON-path-like ("intent_args.post_checks[0].expected_pattern")
  * hint         — concrete fix instruction ("rename 'expected' → 'expected_pattern'")
  * severity     — "error" (blocks submit) | "warning" (allows but flags)

LLM revision loop reads these and produces a targeted fix.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Literal

from olav.core.cab.schemas import DraftChangePlan


@dataclass
class LintError:
    code: str
    message: str
    field: str = ""
    hint: str = ""
    severity: Literal["error", "warning"] = "error"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

# Common typo / synonym table — LLM often uses these instead of the
# canonical field names. Catch each with a specific actionable hint.
_POST_CHECK_FIELD_SYNONYMS = {
    "expected_pattern": ["expected", "pattern", "match", "expect"],
    "command": ["cmd", "show_command"],
    "device": ["host", "target", "node"],
    "description": ["desc", "purpose", "what"],
}


def _check_post_check_entry(pc: dict, idx: int, scope: list[str]) -> list[LintError]:
    errors: list[LintError] = []
    field_prefix = f"intent_args.post_checks[{idx}]"

    if not isinstance(pc, dict):
        return [LintError(
            code="post_check_not_dict",
            message=f"post_checks[{idx}] is not a dict ({type(pc).__name__})",
            field=field_prefix,
            hint="post_check must be a JSON object with device/command/expected_pattern/description",
        )]

    # Canonical field presence + synonym detection
    for canonical, synonyms in _POST_CHECK_FIELD_SYNONYMS.items():
        if not pc.get(canonical):
            # Hard-fail on missing canonical
            wrong = next((s for s in synonyms if s in pc), None)
            if wrong:
                errors.append(LintError(
                    code="post_check_wrong_field_name",
                    message=f"post_checks[{idx}] uses '{wrong}' but canonical name is '{canonical}'",
                    field=f"{field_prefix}.{canonical}",
                    hint=f"Rename '{wrong}' → '{canonical}' (and remove the old key).",
                ))
            elif canonical in ("device", "command", "expected_pattern"):
                # device/command/expected_pattern are required; description optional
                errors.append(LintError(
                    code="post_check_missing_required_field",
                    message=f"post_checks[{idx}] missing required field '{canonical}'",
                    field=f"{field_prefix}.{canonical}",
                    hint=f"Add {canonical!r} key with a non-empty value.",
                ))

    # Specific: expected_pattern empty string is a false-PASS landmine
    ep = pc.get("expected_pattern")
    if isinstance(ep, str) and not ep.strip():
        errors.append(LintError(
            code="post_check_expected_pattern_empty",
            message=f"post_checks[{idx}].expected_pattern is empty — would always-PASS",
            field=f"{field_prefix}.expected_pattern",
            hint=("Empty expected_pattern matches anything → false PASS. "
                  "Use a substring or regex that proves the change took effect "
                  "(e.g. 'FULL' for OSPF adjacency, '192.0.2.0/24' for static route)."),
        ))

    # device must be in scope
    dev = pc.get("device")
    if dev and scope and dev not in scope:
        errors.append(LintError(
            code="post_check_device_not_in_scope",
            message=f"post_checks[{idx}].device={dev!r} not in devices_in_scope {scope}",
            field=f"{field_prefix}.device",
            hint=f"Either add {dev!r} to devices_in_scope, or change device to one of {scope}.",
        ))

    return errors


def _check_cli_per_device(cli_map: Any, scope: list[str], slot: str) -> list[LintError]:
    """Check cli_per_device / rollback_per_device shape: dict[dev, list[str]] covering scope."""
    errors: list[LintError] = []
    if not isinstance(cli_map, dict):
        return [LintError(
            code=f"{slot}_not_dict",
            message=f"intent_args.{slot} is not a dict ({type(cli_map).__name__})",
            field=f"intent_args.{slot}",
            hint=f"{slot} must be {{<device>: [<cli line>, ...]}}",
        )]

    missing = [d for d in scope if d not in cli_map or not cli_map[d]]
    if missing:
        errors.append(LintError(
            code=f"{slot}_missing_devices",
            message=f"intent_args.{slot} missing entries for {missing}",
            field=f"intent_args.{slot}",
            hint=f"Add {{ {missing[0]!r}: [<configure terminal>, <CLI lines>, <end>], ... }} for each.",
        ))

    for d, lines in cli_map.items():
        if not isinstance(lines, list):
            errors.append(LintError(
                code=f"{slot}_value_not_list",
                message=f"intent_args.{slot}[{d!r}] is {type(lines).__name__}, must be list[str]",
                field=f"intent_args.{slot}.{d}",
                hint="Split CLI into a list of strings, one command per element.",
            ))

    return errors


# ────────────────────────────────────────────────────────────────────
# Per-intent lint
# ────────────────────────────────────────────────────────────────────

def _lint_freeform_cli(draft: DraftChangePlan) -> list[LintError]:
    errors: list[LintError] = []
    scope = list(draft.devices_in_scope)
    args = draft.intent_args

    errors.extend(_check_cli_per_device(args.get("cli_per_device"), scope, "cli_per_device"))
    errors.extend(_check_cli_per_device(args.get("rollback_per_device"), scope, "rollback_per_device"))

    pcs = args.get("post_checks") or []
    if not pcs:
        # Synonyms for the post_checks slot itself
        for syn in ("post_check", "postchecks", "checks", "verification"):
            if syn in args:
                errors.append(LintError(
                    code="intent_args_wrong_slot_name",
                    message=f"intent_args uses '{syn}' but canonical name is 'post_checks'",
                    field=f"intent_args.post_checks",
                    hint=f"Rename '{syn}' → 'post_checks' (note the 's').",
                ))
                break
        else:
            errors.append(LintError(
                code="post_checks_missing",
                message="intent_args.post_checks is empty",
                field="intent_args.post_checks",
                hint="Add at least 1 post_check that proves the change took effect. "
                     "Empty post_checks means no automated verification → CAB cannot pass.",
            ))
    else:
        if not isinstance(pcs, list):
            errors.append(LintError(
                code="post_checks_not_list",
                message=f"intent_args.post_checks is {type(pcs).__name__}, must be list",
                field="intent_args.post_checks",
            ))
        else:
            for i, pc in enumerate(pcs):
                errors.extend(_check_post_check_entry(pc, i, scope))

    return errors


def _lint_ebgp_direct(draft: DraftChangePlan) -> list[LintError]:
    # Most ebgp_direct schema is enforced by feasibility check; just a few cross-cutting checks here
    errors: list[LintError] = []
    if len(draft.devices_in_scope) != 2:
        errors.append(LintError(
            code="ebgp_direct_wrong_device_count",
            message=f"ebgp_direct requires exactly 2 devices; got {len(draft.devices_in_scope)}",
            field="devices_in_scope",
        ))
    return errors


_PER_INTENT_LINT = {
    "freeform_cli": _lint_freeform_cli,
    "ebgp_direct": _lint_ebgp_direct,
}


# ────────────────────────────────────────────────────────────────────
# Cross-cutting (intent-independent)
# ────────────────────────────────────────────────────────────────────

def _lint_facts_completeness(draft: DraftChangePlan) -> list[LintError]:
    errors: list[LintError] = []
    facts = draft.facts_collected
    scope = list(draft.devices_in_scope)

    # Every device in scope should be in facts.devices
    fact_names = {d.name for d in facts.devices}
    missing = [d for d in scope if d not in fact_names]
    if missing:
        errors.append(LintError(
            code="facts_devices_missing",
            message=f"devices_in_scope has {missing} but facts_collected.devices doesn't",
            field="facts_collected.devices",
            hint=f"Call inspect_devices({missing}) and include the result in facts_collected.devices.",
        ))

    # Multi-device + topology-dependent intent → topology_edges must be non-empty
    needs_topology = draft.proposed_intent in (
        "ebgp_direct", "ibgp_direct", "freeform_cli",
    )
    if len(scope) >= 2 and needs_topology and not facts.topology_edges:
        errors.append(LintError(
            code="facts_topology_edges_missing",
            message=(
                f"Multi-device {draft.proposed_intent} draft but "
                f"facts_collected.topology_edges is empty"
            ),
            field="facts_collected.topology_edges",
            hint=(
                f"Call inspect_topology({scope}), then add every edge to "
                f"facts_collected.topology_edges as "
                f"{{source_device, source_interface, destination_device, destination_interface}}."
            ),
            severity="error" if draft.proposed_intent == "ebgp_direct" else "warning",
        ))

    return errors


def _lint_rationale(draft: DraftChangePlan) -> list[LintError]:
    errors: list[LintError] = []
    rationale = (draft.rationale or "").strip()
    if len(rationale) < 30:
        errors.append(LintError(
            code="rationale_too_short",
            message=f"rationale is only {len(rationale)} chars; must be ≥30",
            field="rationale",
            hint=(
                "Explain WHY this intent + this device list. Reference what you "
                "observed via inspect_* tools (e.g. 'inspect_devices showed R1.local_as=65000 "
                "matching R3, so iBGP not eBGP')."
            ),
        ))
    return errors


# ────────────────────────────────────────────────────────────────────
# Public entry
# ────────────────────────────────────────────────────────────────────

def lint_draft(draft: DraftChangePlan) -> list[LintError]:
    """Run all applicable lint rules. Returns flat list of errors (empty = clean)."""
    errors: list[LintError] = []
    errors.extend(_lint_rationale(draft))
    errors.extend(_lint_facts_completeness(draft))
    per_intent = _PER_INTENT_LINT.get(draft.proposed_intent)
    if per_intent:
        errors.extend(per_intent(draft))
    return errors

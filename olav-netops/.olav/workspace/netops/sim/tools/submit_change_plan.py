"""submit_change_plan @tool — sim's deliverable.

R-AGENT-HIERARCHY Phase D (2026-05-09): replaces the
`## Change Summary` YAML block + render_tcf skill-script pattern
with a single structured-output tool call.

The Pydantic schema is grammar-constrained at LLM decode time
via LangChain's tool-calling channel (the same JSON schema the
LLM provider sees for structured output).  The free-form
``rationale`` and ``steps`` prose fields give the LLM a place
to put its analytical work without escaping the schema.

Two-channel design:
  * Schema-constrained: intent (enum), devices (typed list),
    feasibility (enum) — facts that drive deterministic rendering
  * Free-form prose: summary, rationale, steps — analysis text

The tool:
  1. Composes a Markdown change plan from the structured + prose fields
  2. Saves it to ``exports/change_plans/<change_id>.md``
  3. Calls ``render_tcf_from_change_plan`` to ground facts from DB
     and render TCF YAML
  4. Returns an envelope with both paths + grounded facts
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import tool


# Module-level so tests can patch
_MAX_DEVICES = 4


def _slugify(s: str) -> str:
    """Compress a string into a filesystem-safe slug."""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", s).strip("-").lower()
    return s[:60] or "change"


_INSPECT_CITE_RE = re.compile(r"\binspect_[a-z_]+\b")


def _compose_plan_md(
    *,
    intent: str,
    devices: list[str],
    summary: str,
    rationale: str,
    steps: str,
    feasibility: str,
    feasibility_reason: str,
    change_id: str,
    facts_cited: list[str],
    freeform_cli_per_device: dict[str, list[str]] | None = None,
    freeform_rollback_per_device: dict[str, list[str]] | None = None,
    freeform_pre_checks: list[dict[str, Any]] | None = None,
    freeform_post_checks: list[dict[str, Any]] | None = None,
) -> str:
    """Build the Markdown plan body from structured + prose fields.

    The trailing ``## Change Summary`` block is emitted so the
    deterministic ``render_tcf_from_change_plan`` parser can pick
    it up — but the LLM never authored that block, the tool did.
    """
    parts: list[str] = [f"# Change Plan: {summary}", ""]
    parts.append(f"**Change ID**: `{change_id}`")
    parts.append(f"**Intent**: `{intent}`")
    parts.append(f"**Devices**: {', '.join(devices)}")
    parts.append(f"**Feasibility**: {feasibility}")
    if feasibility_reason:
        parts.append(f"**Feasibility reason**: {feasibility_reason}")
    parts.append("")
    if rationale.strip():
        parts.extend(["## Rationale", "", rationale.strip(), ""])
    if facts_cited:
        # ARCH-35: HITL audit trail — every change must cite the
        # inspect_* tool outputs that grounded its decisions.
        parts.extend(["## Facts cited", ""])
        for fc in facts_cited:
            parts.append(f"- {fc}")
        parts.append("")
    if steps.strip():
        parts.extend(["## Steps", "", steps.strip(), ""])
    # Trailing summary block — for the deterministic renderer.
    parts.extend([
        "## Change Summary",
        "",
        "```yaml",
        f"change_id: {change_id}",
        f"title: {summary}",
        f"intent_type: {intent}",
        f"devices: {devices}",
        f"feasibility: {feasibility}",
    ])
    if feasibility_reason:
        parts.append(f'feasibility_reason: "{feasibility_reason}"')
    # Freeform CLI / checks payload (only present when intent=freeform_cli)
    if intent == "freeform_cli":
        import yaml as _yaml
        ff_payload = {
            "cli_per_device": freeform_cli_per_device or {},
            "rollback_per_device": freeform_rollback_per_device or {},
            "pre_checks": freeform_pre_checks or [],
            "post_checks": freeform_post_checks or [],
        }
        ff_yaml = _yaml.safe_dump(
            ff_payload, sort_keys=False, default_flow_style=False
        )
        # Embed each top-level key inline in the YAML block
        parts.append(ff_yaml.rstrip())
    parts.extend(["```", ""])
    return "\n".join(parts)


@tool
def submit_change_plan(
    intent: Literal["ebgp_direct", "freeform_cli"],
    devices: list[str],
    summary: str,
    rationale: str = "",
    steps: str = "",
    feasibility: Literal["OK", "OK_HITL_ONLY", "BLOCKED"] = "OK",
    feasibility_reason: str = "",
    change_id: str = "",
    facts_cited: list[str] | None = None,
    output_root: str = "exports",
    cli_per_device: dict[str, list[str]] | None = None,
    rollback_per_device: dict[str, list[str]] | None = None,
    pre_checks: list[dict[str, Any]] | None = None,
    post_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Submit your change plan.  This is sim's deliverable — calling
    this tool ENDS your loop.

    The schema-constrained fields (`intent`, `devices`, `feasibility`)
    drive deterministic TCF rendering — the Python writer queries the
    DB for ASN / loopback / platform per device and renders complete,
    deployable CLI from per-platform templates.  You do NOT pass any
    of those facts; trying to fabricate them would be ignored.

    The free-form prose fields (`summary`, `rationale`, `steps`) are
    YOUR analytical container.  Write them as Markdown.  They become
    the human-readable change-plan artifact (saved to
    `exports/change_plans/<change_id>.md`) that the user reviews
    before lab validation.

    Args:
        intent: What kind of change.

            ``ebgp_direct`` — direct eBGP session between 2 devices
                in different ASNs.  Python composes CLI from DB facts
                + per-platform templates.  No CLI args needed.

            ``freeform_cli`` — any other change type (static route,
                OSPF, VLAN, ACL, MTU, interface description, ...).
                You provide CLI directly via ``cli_per_device`` /
                ``rollback_per_device`` and check intents via
                ``pre_checks`` / ``post_checks``.  CLI must be
                grounded in inspector outputs (e.g. interface IP from
                inspect_devices, neighbor IP from inspect_topology).
        devices: List of device hostnames (1-4).  Must match
            ``netops.devices.hostname`` values.
        summary: One-line title for the change.  Becomes the TCF
            ``title`` and the Markdown ``# Change Plan:`` header.
        rationale: WHY this change is being proposed.  Free-form
            Markdown.  Multiple paragraphs OK.  Optional.
        steps: HOW the change will be applied — describe the
            deployment phases, pre-checks, and verification steps.
            Free-form Markdown.  Optional.  (The Python writer
            generates the actual CLI from templates; your `steps`
            text is for human reviewers.)
        feasibility: ``OK`` if you verified the change is feasible
            and lab validation should proceed. **For ``freeform_cli``
            intent, use OK** — the lab pipeline now has a prose-mode
            LLM translator that produces SRL CLI from your prod CLI
            (commit `0af7953` + `01d4a64`), so freeform changes can
            be validated automatically.

            ``OK_HITL_ONLY`` is reserved for the rare case where sim
            verified feasibility but knows the change requires human-
            only review (e.g., touches credentials, security policies,
            or contains commands beyond the SRL translator's known
            patterns). When in doubt, prefer ``OK`` and let lab
            validation surface any translation/verification issue
            via its FAIL verdict — that is more informative than
            preemptive HITL.

            ``BLOCKED`` if you found a hard blocker (same-AS for
            eBGP, missing inspector data, infeasible topology, etc.).
        feasibility_reason: One-line reason if feasibility=BLOCKED.
        change_id: Optional explicit change ID; auto-generated from
            devices + intent if empty.
        facts_cited: List of strings citing the inspect_* tool outputs
            you used to ground this plan.  Each entry should NAME the
            inspect_* tool and the fact it provided, e.g.
            ``"inspect_devices: R3.local_as=65000, R4.local_as=65001"``,
            ``"inspect_topology: R3-R4 directly connected on Gi0/2 ↔ Gi0/2"``,
            ``"inspect_blast_radius: removing R4 isolates SW1; this
              change adds redundant path"``.
            HITL reviewers use this list to verify the plan is grounded
            in real data, not hallucination.  Empty list earns a warning
            but doesn't block (soft enforcement until fine-tuning lands;
            see ADR-0010).
        output_root: Where ``change_plans/`` and ``cab/`` go.
            Default ``"exports"``.
        cli_per_device: REQUIRED for ``intent='freeform_cli'``; ignored
            otherwise.  Dict mapping device hostname → list of CLI
            command strings to apply.  Must cover every device in
            ``devices``.  Lines are concatenated with newlines into
            the TCF ``implementation`` block.  Example::

                {"R3": [
                    "configure terminal",
                    "ip route 192.0.2.0 255.255.255.0 10.0.13.1",
                    "end",
                    "write memory",
                ]}

            The IP ``10.0.13.1`` MUST come from an inspect_* call; do
            not invent it.
        rollback_per_device: REQUIRED for ``freeform_cli``.  Same
            shape as ``cli_per_device``; CLI to undo the change if
            post_check fails.  Example::

                {"R3": [
                    "configure terminal",
                    "no ip route 192.0.2.0 255.255.255.0 10.0.13.1",
                    "end",
                    "write memory",
                ]}

        pre_checks: Optional for freeform_cli.  Each entry is a dict
            with keys: ``device`` (must be in devices list),
            ``command`` (show command to run), ``expected_pattern``
            (substring to look for in output), ``must_match`` (bool —
            True = pattern presence is OK, False = pattern absence is
            OK), ``description`` (human-readable purpose).  Used to
            gate implementation: any pre_check failure blocks the
            change.  Example::

                [{"device": "R3",
                  "command": "show ip route 192.0.2.0",
                  "expected_pattern": "Network not in table",
                  "must_match": True,
                  "description": "Confirm route doesn't exist before adding"}]

        post_checks: REQUIRED for freeform_cli (TVT needs evidence to
            reference).  Same dict shape as pre_checks but no
            ``must_match`` (always True).  Used to verify the change
            took effect.  Example::

                [{"device": "R3",
                  "command": "show ip route 192.0.2.0",
                  "expected_pattern": "192.0.2.0/24",
                  "description": "Static route installed in RIB"}]

    Returns:
        On feasibility=OK:
            {"status": "ok",
             "plan_md_path": "exports/change_plans/<id>.md",
             "spec_path": "exports/cab/<id>/spec.tcf.yaml",
             "facts": {<device>: {platform, loopback, local_as}},
             "warnings": [...]}
        On feasibility=BLOCKED or DB-derived blocker:
            {"status": "error",
             "error": "...",
             "blockers": [...],
             "plan_md_path": "<id>.md",
             "facts": {...}}

    Example:
        >>> submit_change_plan(
        ...     intent="ebgp_direct",
        ...     devices=["R2", "R3"],
        ...     summary="Add eBGP between R2 and R3",
        ...     rationale=(
        ...         "R2 (AS 65001) and R3 (AS 65000) currently rely on "
        ...         "transit through R4 for reachability.  Direct "
        ...         "eBGP gives a redundant path."
        ...     ),
        ...     steps=(
        ...         "Phase 1: configure both devices.\\n"
        ...         "Phase 2: verify session reaches Established within 60s."
        ...     ),
        ...     feasibility="OK",
        ... )
    """
    from olav.core.cab import render_tcf_from_change_plan

    if not (1 <= len(devices) <= _MAX_DEVICES):
        return {
            "status": "error",
            "error": (
                f"devices must have 1-{_MAX_DEVICES} entries; "
                f"got {len(devices)}: {devices!r}"
            ),
        }

    if not change_id:
        change_id = _slugify(f"{'-'.join(devices)}-{intent.split('_')[0]}")

    # ARCH-35: validate facts_cited — soft enforcement on initial roll-out.
    # Each citation should reference at least one inspect_* tool output;
    # an empty list when feasibility=OK earns a warning but doesn't block.
    # Once fine-tuning lands (ADR-0010 graduation), this becomes a hard
    # requirement.
    facts_cited_list = list(facts_cited or [])
    fc_warnings: list[str] = []
    if feasibility == "OK" and not facts_cited_list:
        fc_warnings.append(
            "facts_cited is empty — HITL reviewers cannot trace which "
            "inspect_* outputs grounded this plan.  Recommended: cite at "
            "least inspect_devices, inspect_topology, and (for change "
            "planning) inspect_blast_radius."
        )
    else:
        for entry in facts_cited_list:
            if not _INSPECT_CITE_RE.search(entry):
                fc_warnings.append(
                    f"facts_cited entry {entry!r} does not name an "
                    f"inspect_* tool — entries should reference the tool "
                    f"that produced the fact, e.g. "
                    f"'inspect_devices: R3.local_as=65000'."
                )

    # Validate freeform_cli prerequisites before YAML composition.
    # OK_HITL_ONLY uses the same slot requirements as OK because the
    # spec.tcf.yaml + plan.md still have to render — only the
    # downstream lab dispatch differs (per ADR-0011 §5).
    if intent == "freeform_cli" and feasibility in ("OK", "OK_HITL_ONLY"):
        if not cli_per_device:
            return {
                "status": "error",
                "error": (
                    "intent='freeform_cli' with feasibility=OK requires "
                    "cli_per_device (device → CLI lines) — sim must "
                    "provide CLI grounded in inspect_* outputs"
                ),
            }
        if not rollback_per_device:
            return {
                "status": "error",
                "error": (
                    "intent='freeform_cli' with feasibility=OK requires "
                    "rollback_per_device — every change must have a "
                    "rollback path"
                ),
            }
        if not post_checks:
            return {
                "status": "error",
                "error": (
                    "intent='freeform_cli' with feasibility=OK requires "
                    "at least one post_check — TVT needs verification "
                    "evidence to reference"
                ),
            }

    # Compose the prose plan + trailing Summary block (block is for the
    # deterministic renderer; never seen by the LLM).
    plan_md = _compose_plan_md(
        intent=intent,
        devices=devices,
        summary=summary,
        rationale=rationale,
        steps=steps,
        feasibility=feasibility,
        feasibility_reason=feasibility_reason,
        change_id=change_id,
        facts_cited=facts_cited_list,
        freeform_cli_per_device=cli_per_device,
        freeform_rollback_per_device=rollback_per_device,
        freeform_pre_checks=pre_checks,
        freeform_post_checks=post_checks,
    )

    # Save the human-readable .md artifact for HITL review
    plan_md_dir = Path(output_root) / "change_plans"
    plan_md_dir.mkdir(parents=True, exist_ok=True)
    plan_md_path = plan_md_dir / f"{change_id}.md"
    plan_md_path.write_text(plan_md, encoding="utf-8")

    # Render TCF deterministically (DB-grounded facts, template CLI)
    cab_dir = Path(output_root) / "cab"
    result = render_tcf_from_change_plan(
        plan_md,
        output_dir=str(cab_dir),
        created_by="sim",
    )

    # Always include the .md path so the agent can report HITL artifact
    if isinstance(result, dict):
        result["plan_md_path"] = str(plan_md_path)
        # ARCH-35: surface facts_cited warnings to the LLM so it can
        # patch up the plan in the next iteration if needed.  Don't
        # block — soft enforcement until fine-tune graduation.
        if fc_warnings:
            existing = result.get("warnings") or []
            result["warnings"] = (
                list(existing) + fc_warnings
                if isinstance(existing, list)
                else fc_warnings
            )
        result["facts_cited_count"] = len(facts_cited_list)
        # P1 (2026-05-10, dev_docs/74 follow-on): emit a structured
        # next_step hint so the orchestrator knows what to chain to.
        # Soft enforcement — the orchestrator's compound-chain guide
        # references this field; hard enforcement can come later via
        # middleware.
        if result.get("status") in ("ok", "success") and feasibility == "OK":
            result["next_step"] = {
                "action": "lab_validate",
                "sub_agent": "lab",
                "args": {"spec_path": result.get("spec_path")},
                "hint": (
                    "Plan emitted feasibility=OK.  If user requested "
                    "validation in lab (keywords: 'validate', 'verify', "
                    "'test', '验证', 'CAB'), follow up with "
                    f"task('lab', '{result.get('spec_path')}').  "
                    "Otherwise present the spec_path for HITL approval."
                ),
            }
        elif feasibility == "OK_HITL_ONLY":
            # ADR-0011 §5: lab digital twin can't deterministically
            # validate this change type.  Spec + plan are emitted for
            # HITL but lab dispatch is skipped.
            result["next_step"] = {
                "action": "hitl_review",
                "args": {
                    "spec_path": result.get("spec_path"),
                    "plan_md_path": result.get("plan_md_path"),
                },
                "hint": (
                    f"Plan emitted feasibility=OK_HITL_ONLY ({feasibility_reason!r}).  "
                    "Sim verified the change is feasible, but the lab "
                    "digital twin cannot deterministically validate this "
                    "intent (typical for freeform_cli — R89 SRL renderer "
                    "scope).  Do NOT call task('lab', ...).  Surface the "
                    "spec_path + plan_md_path to the user for manual "
                    "review and prod application."
                ),
            }
        elif feasibility != "OK":
            result["next_step"] = {
                "action": "report_blocked",
                "hint": (
                    f"Plan emitted feasibility={feasibility!r}.  Do NOT "
                    "validate in lab — surface the blocker to the user "
                    "and ask for a revised request."
                ),
            }
    return result

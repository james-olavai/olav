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
    parts.extend(["```", ""])
    return "\n".join(parts)


@tool
def submit_change_plan(
    intent: Literal["ebgp_direct", "ibgp_direct", "vlan_add"],
    devices: list[str],
    summary: str,
    rationale: str = "",
    steps: str = "",
    feasibility: Literal["OK", "BLOCKED"] = "OK",
    feasibility_reason: str = "",
    change_id: str = "",
    output_root: str = "exports",
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
        intent: What kind of change.  ``ebgp_direct`` = direct eBGP
            session between 2 devices in different ASNs.
            ``ibgp_direct`` = iBGP between 2 devices in the same AS.
            ``vlan_add`` = add a VLAN trunk between 2 switches.
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
            (e.g. ASNs differ for ebgp_direct).  ``BLOCKED`` if your
            feasibility check found a hard blocker.
        feasibility_reason: One-line reason if feasibility=BLOCKED.
        change_id: Optional explicit change ID; auto-generated from
            devices + intent if empty.
        output_root: Where ``change_plans/`` and ``cab/`` go.
            Default ``"exports"``.

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
    return result

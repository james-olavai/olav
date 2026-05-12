"""Sim atomic entry point — finalize_tcf_from_draft(draft_path).

R-CAB-THREE-STAGE Day 4 (2026-05-12, dev_docs/75).

Single function the orchestrator calls. NEVER raises. Outputs one of:

  * OK    → writes ``<change_id>/spec.tcf.yaml`` and returns
            {"status": "ok", "spec_path": ...,
             "next_step": {"action": "lab_validate", ...}}
  * REJ   → writes ``<change_id>/rejection_sim.yaml`` and returns
            {"status": "rejected", "rejection_path": ...,
             "next_step": {"action": "analyzer_revise", ...}}
  * ERR   → file load / parse failure; no disk write
            {"status": "error", "error": "..."}

The renderer is the existing ``render_tcf_from_change_plan`` (a thin
adapter rebuilds the Markdown change-plan envelope it expects from
the DraftChangePlan). Day 6 will replace this adapter with a
direct Pydantic→CabTcf path, but for the cutover the adapter is the
safest route — the legacy renderer's per-intent dispatch + lab-subnet
allocator + warning emission are battle-tested.
"""
from __future__ import annotations

import io
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from olav.core.cab.schemas import (
    DEFAULT_MAX_RETRIES,
    DraftChangePlan,
    FeasibilityVerdict,
    LabRejectionReport,
    RejectionReport,
)
from olav.core.cab.sim.feasibility import check_feasibility
from olav.core.cab.sim.simulator import simulate_change


def _change_id_from_path(draft_path: Path) -> str:
    """Convention: drafts live at <output_root>/<change_id>/draft.yaml."""
    return draft_path.parent.name


def _draft_to_plan_md(draft: DraftChangePlan, change_id: str) -> str:
    """Build the Markdown body that ``render_tcf_from_change_plan`` parses.

    The legacy renderer extracts a YAML block under ``## Change Summary``;
    everything else in the Markdown is human-facing rationale.
    """
    title = draft.user_prompt[:80] or change_id
    summary: dict[str, Any] = {
        "change_id": change_id,
        "title": title,
        "intent_type": draft.proposed_intent,
        "devices": list(draft.devices_in_scope),
        "feasibility": "OK",
    }
    if draft.intent_args:
        summary["intent_args"] = dict(draft.intent_args)
    # freeform_cli puts CLI/rollback/checks at the top level, not
    # nested under intent_args. Promote them so the legacy renderer
    # finds them in summary[*].
    if draft.proposed_intent == "freeform_cli":
        for key in ("cli_per_device", "rollback_per_device",
                    "pre_checks", "post_checks"):
            if key in draft.intent_args:
                summary[key] = draft.intent_args[key]

    buf = io.StringIO()
    buf.write(f"# Change Plan: {title}\n\n")
    buf.write(f"## Rationale\n\n{draft.rationale}\n\n")
    buf.write("## Change Summary\n\n```yaml\n")
    yaml.safe_dump(summary, buf, sort_keys=False)
    buf.write("```\n")
    return buf.getvalue()


def _write_rejection(
    *,
    change_id: str,
    cab_dir: Path,
    verdict: FeasibilityVerdict,
    revision_round: int,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timestamp: datetime | None = None,
) -> tuple[Path, bool]:
    """Persist the rejection. Returns (path, hard_blocked).

    Sets ``hard_blocked=True`` when the analyzer has exhausted its
    revision budget — the schema invariant requires
    ``revision_round >= max_retries`` for hard_blocked, so the bound
    here is intentionally inclusive.
    """
    cab_dir.mkdir(parents=True, exist_ok=True)
    hard_blocked = revision_round >= max_retries
    rej = RejectionReport(
        rejected_at=timestamp or datetime.now(tz=UTC),
        rejected_by="sim",
        draft_change_id=change_id,
        revision_round=revision_round,
        blockers=list(verdict.blockers),
        suggested_alternatives=list(verdict.suggested_alternatives),
        hard_blocked=hard_blocked,
        max_retries=max_retries,
    )
    path = cab_dir / "rejection_sim.yaml"
    path.write_text(
        yaml.safe_dump(rej.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    return path, hard_blocked


def finalize_tcf_from_draft(draft_path: str | Path) -> dict[str, Any]:
    """Single deterministic pipeline call. NEVER raises.

    Stage order:
      1. load + Pydantic-validate the draft
      2. check_feasibility (Day-3 per-intent rule)  → BLOCKED ends here
      3. simulate_change (Day-4 networkx mutation)  → fail-flags end here
      4. render via legacy ``render_tcf_from_change_plan``
      5. return next_step envelope
    """
    p = Path(draft_path)
    if not p.exists():
        return {"status": "error", "error": f"draft_path not found: {p}"}

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return {"status": "error", "error": f"yaml parse failed: {e}"}

    try:
        draft = DraftChangePlan.model_validate(raw)
    except ValidationError as e:
        return {"status": "error", "error": f"draft schema invalid: {e}"}

    change_id = _change_id_from_path(p)
    cab_dir = p.parent

    # Stage 2 — feasibility
    verdict = check_feasibility(draft)
    if verdict.feasibility == "BLOCKED":
        rej_path, hard_blocked = _write_rejection(
            change_id=change_id,
            cab_dir=cab_dir,
            verdict=verdict,
            revision_round=draft.revision_round,
        )
        return {
            "status": "hard_blocked" if hard_blocked else "rejected",
            "rejection_path": str(rej_path),
            "blockers": [b.code for b in verdict.blockers],
            "hard_blocked": hard_blocked,
            "next_step": {
                "action": "user_review" if hard_blocked else "analyzer_revise",
                "sub_agent": "user" if hard_blocked else "analyzer",
                "args": {"change_id": change_id,
                          "rejection_path": str(rej_path)},
                "hint": (
                    f"Hard-blocked after {draft.revision_round} revisions "
                    f"(blockers: {[b.code for b in verdict.blockers]}). "
                    f"Surface to user."
                ) if hard_blocked else (
                    f"Sim rejected the draft with blockers "
                    f"{[b.code for b in verdict.blockers]}. Analyzer "
                    f"should call receive_rejection then re-submit."
                ),
            },
        }

    # Stage 3 — simulate (Day 4 MVP: structural checks only)
    sim_report = simulate_change(draft)
    fail_flags = {f for f in sim_report.risk_flags
                  if f in {"routing_loop_introduced", "device_isolated",
                            "existing_session_broken"}}
    if fail_flags:
        # Convert sim failure → feasibility-style rejection so the
        # analyzer sees one consistent envelope shape.
        from olav.core.cab.schemas import Blocker
        sim_blockers = [
            Blocker(code=f, message=f"simulator flagged {f}",
                    evidence={"sim_report": sim_report.model_dump()})
            for f in fail_flags
        ]
        synth_verdict = FeasibilityVerdict(
            chosen_intent=draft.proposed_intent,
            feasibility="BLOCKED",
            blockers=sim_blockers,
        )
        rej_path, hard_blocked = _write_rejection(
            change_id=change_id,
            cab_dir=cab_dir,
            verdict=synth_verdict,
            revision_round=draft.revision_round,
        )
        return {
            "status": "hard_blocked" if hard_blocked else "rejected",
            "rejection_path": str(rej_path),
            "blockers": [b.code for b in sim_blockers],
            "hard_blocked": hard_blocked,
            "next_step": {
                "action": "user_review" if hard_blocked else "analyzer_revise",
                "sub_agent": "user" if hard_blocked else "analyzer",
                "args": {"change_id": change_id,
                          "rejection_path": str(rej_path)},
            },
        }

    # Stage 4 — native render (no DB, no plan_md, no LLM)
    # ──────────────────────────────────────────────────────────────────
    # 2026-05-13 cleanup: legacy ``render_tcf_from_change_plan`` adapter
    # is gone. Native renderers in ``sim/render/<intent>.py`` consume
    # the draft directly and produce a typed CabTcf — no DB queries,
    # no Markdown intermediate. Fall back to legacy ONLY for intents
    # without a native renderer (deprecation window).
    try:
        from olav.core.cab.sim.render import RENDERERS as _NATIVE_RENDERERS
        from olav.core.cab.lab_subnet_pool import allocate_lab_subnet
        if draft.proposed_intent in _NATIVE_RENDERERS:
            lab_subnet = allocate_lab_subnet(change_id)
            tcf = _NATIVE_RENDERERS[draft.proposed_intent](
                draft, lab_subnet, change_id
            )
            spec_p = cab_dir / "spec.tcf.yaml"
            spec_p.write_text(
                yaml.safe_dump(tcf.model_dump(mode="json"), sort_keys=False),
                encoding="utf-8",
            )
            spec_path = str(spec_p)
            result = {"status": "ok", "spec_path": spec_path}
        else:
            # Legacy fallback (still calls _db_facts internally — to be
            # removed once native renderers for ebgp_direct / ibgp /
            # static_route / vlan_add all land).
            from olav.core.cab.tcf_writer import render_tcf_from_change_plan
            plan_md = _draft_to_plan_md(draft, change_id)
            output_dir = cab_dir.parent
            result = render_tcf_from_change_plan(
                plan_md, output_dir=str(output_dir), created_by="sim",
            )
    except Exception as e:  # NEVER raises
        return {
            "status": "error",
            "error": f"render failed: {e!r}",
            "change_id": change_id,
        }

    if result.get("status") not in {"ok", "success"}:
        from olav.core.cab.schemas import Blocker
        msg = str(result.get("error") or "render returned non-ok status")
        synth = FeasibilityVerdict(
            chosen_intent=draft.proposed_intent,
            feasibility="BLOCKED",
            blockers=[Blocker(
                code="render_failed",
                message=msg,
                evidence={"render_result": result},
            )],
        )
        rej_path, hard_blocked = _write_rejection(
            change_id=change_id, cab_dir=cab_dir,
            verdict=synth, revision_round=draft.revision_round,
        )
        return {
            "status": "hard_blocked" if hard_blocked else "rejected",
            "rejection_path": str(rej_path),
            "blockers": ["render_failed"],
            "hard_blocked": hard_blocked,
            "next_step": {
                "action": "user_review" if hard_blocked else "analyzer_revise",
                "sub_agent": "user" if hard_blocked else "analyzer",
                "args": {"change_id": change_id,
                          "rejection_path": str(rej_path)},
            },
        }

    spec_path = result.get("spec_path")

    # Topology backfill for legacy-rendered specs only — native
    # renderers already write topology_links upfront.
    if spec_path and draft.facts_collected.topology_edges \
       and draft.proposed_intent not in _NATIVE_RENDERERS:
        try:
            spec_p = Path(spec_path)
            spec = yaml.safe_load(spec_p.read_text(encoding="utf-8"))
            if isinstance(spec, dict) and not spec.get("topology_links"):
                spec["topology_links"] = [
                    {
                        "source_device": e.source_device,
                        "source_interface": e.source_interface,
                        "destination_device": e.destination_device,
                        "destination_interface": e.destination_interface,
                        "discovery_protocol": e.discovery_protocol,
                    }
                    for e in draft.facts_collected.topology_edges
                ]
                spec_p.write_text(
                    yaml.safe_dump(spec, sort_keys=False),
                    encoding="utf-8",
                )
        except Exception:  # NEVER raise — degrade gracefully
            pass

    return {
        "status": "ok",
        "change_id": change_id,
        "spec_path": spec_path,
        "sim_report": sim_report.model_dump(),
        "next_step": {
            "action": "lab_validate",
            "sub_agent": "lab",
            "args": {"spec_path": spec_path},
            "hint": (
                f"Spec rendered at {spec_path}. Hand off to lab via "
                f"task('lab', 'validate', {{'spec_path': {spec_path!r}}})."
            ),
        },
    }

"""DraftChangePlan — Analyzer → Sim envelope.

Persisted to ``exports/cab/<change_id>/draft.yaml``. Sim reads it via
``finalize_tcf_from_draft(draft_path)``.

The schema is the contract: empty / unknown fields are refused at
construct time, so the Analyzer cannot accidentally submit a half-
formed draft. This replaces the F.3 hard-error patch on the old
submit_change_plan tool — the patch was needed because the legacy
tool's signature was permissive.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .facts import FactsEnvelope


#: Intents the Sim layer knows how to materialise. Adding a new intent
#: requires (a) a per-intent feasibility rule in
#: ``olav.core.cab.sim.feasibility.<intent>``, (b) either a Python
#: renderer in ``olav.core.cab.sim.render.<intent>`` OR a YAML schema
#: under ``src/olav/data/intent_schemas/<intent>.intent.yaml``.
SupportedIntent = Literal[
    "ebgp_direct",
    "ibgp_direct",
    "static_route_add",
    "vlan_add",
    "freeform_cli",
]


class DraftChangePlan(BaseModel):
    """The Analyzer's proposal. Sim either turns it into a TCF or
    returns a RejectionReport.

    Required: a non-empty FactsEnvelope (grounding evidence) + a
    Literal-validated intent + at least one device in scope. Optional:
    intent-specific args.
    """

    model_config = ConfigDict(extra="forbid")

    # User context
    user_prompt: str = Field(min_length=1)
    devices_in_scope: list[str] = Field(min_length=1)

    # Proposal
    proposed_intent: SupportedIntent
    intent_args: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)

    # Grounding (schema-enforced — replaces F.3 hard-error)
    facts_collected: FactsEnvelope

    # Revision metadata (set by Analyzer on retry after Sim rejection)
    revision_round: int = Field(default=0, ge=0)
    previous_blockers: list[str] = Field(default_factory=list)

    # Optional: where to write artifacts (defaults to exports/cab/<change_id>/)
    output_root: str = "exports/cab"

"""RejectionReport (Sim → Analyzer) and LabRejectionReport (Lab → …).

Persisted to disk:
  exports/cab/<change_id>/rejection_sim.yaml
  exports/cab/<change_id>/rejection_lab.yaml

The Analyzer reads `rejection_sim.yaml` via the `receive_rejection`
tool on its next task() invocation, increments revision_round, and
re-submits a Draft. Lab rejections carry a `routing_hint` field that
the orchestrator uses to mechanically dispatch the next stage.
"""
from __future__ import annotations

from datetime import datetime, UTC
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .feasibility import Blocker, SuggestedAlternative


#: Default max revision rounds before the chain is hard-blocked.
#: Keeps the Analyzer ↔ Sim loop bounded.
DEFAULT_MAX_RETRIES: int = 3


class RejectionReport(BaseModel):
    """Sim's structured rejection of an Analyzer draft.

    `hard_blocked=True` is only valid when revision_round has reached
    the max. This prevents accidental hard-blocks on first try when
    the Analyzer could productively revise.
    """

    model_config = ConfigDict(extra="forbid")

    rejected_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    rejected_by: Literal["sim", "lab"] = "sim"
    draft_change_id: str = Field(min_length=1)
    revision_round: int = Field(ge=0)

    blockers: list[Blocker] = Field(min_length=1)
    suggested_alternatives: list[SuggestedAlternative] = Field(default_factory=list)
    hard_blocked: bool = False

    max_retries: int = DEFAULT_MAX_RETRIES

    @model_validator(mode="after")
    def _hard_blocked_gate(self):
        if self.hard_blocked and self.revision_round < self.max_retries:
            raise ValueError(
                f"hard_blocked=True requires revision_round >= "
                f"max_retries={self.max_retries}; got "
                f"revision_round={self.revision_round}. Set hard_blocked "
                f"only after the Analyzer has had its full revision budget."
            )
        return self


class LabRejectionReport(BaseModel):
    """Lab's structured failure report.

    routing_hint tells the orchestrator who fixes this:
      * sim_can_revise        → tcf_patch_block (Sim re-renders one CLI block)
      * analyzer_intent_wrong → Analyzer picks a different intent
      * infra_problem         → CLAB / auth / network — surface to user
      * user_review           → all retries exhausted; ask the operator
    """

    model_config = ConfigDict(extra="forbid")

    failed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    failed_phase: Literal["pre_check", "deploy", "push", "post_check", "tvt"]
    failed_check_id: str | None = None
    error: str = Field(min_length=1)
    captured_evidence: dict[str, str] = Field(default_factory=dict)
    routing_hint: Literal[
        "sim_can_revise",
        "analyzer_intent_wrong",
        "infra_problem",
        "user_review",
    ]

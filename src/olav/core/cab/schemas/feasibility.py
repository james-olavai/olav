"""FeasibilityVerdict — Sim-internal per-intent rule output.

Not persisted to disk on its own; folded into RejectionReport (on
BLOCKED) or consumed by the simulator/render stages (on OK).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Blocker(BaseModel):
    """A single structured reason a change cannot proceed."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


class SuggestedAlternative(BaseModel):
    """A pointer to a different intent that WOULD work for the user's
    underlying ask. The Analyzer reads these when revising."""

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    required_changes: dict[str, Any] = Field(default_factory=dict)


class FeasibilityVerdict(BaseModel):
    """Result of Sim's per-intent feasibility check.

    feasibility=OK → render the TCF
    feasibility=BLOCKED → wrap blockers + alternatives into a RejectionReport
    """

    model_config = ConfigDict(extra="forbid")

    chosen_intent: str = Field(min_length=1)
    feasibility: Literal["OK", "BLOCKED"]
    blockers: list[Blocker] = Field(default_factory=list)
    suggested_alternatives: list[SuggestedAlternative] = Field(default_factory=list)
    required_args: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _blocked_must_have_blockers(self):
        if self.feasibility == "BLOCKED" and not self.blockers:
            raise ValueError(
                "feasibility=BLOCKED requires at least one Blocker "
                "(a structured rejection has to name a code)"
            )
        return self

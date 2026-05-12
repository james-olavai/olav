"""SimulationReport — networkx mutation result, Sim-internal.

Sim's simulator stage runs the proposed change against an in-memory
graph and reports what would change. Risk flags are enum-validated;
each one maps to a specific Blocker code if it's a failure flag.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


#: Enum-validated risk-flag taxonomy. Adding a new flag requires updating
#: this Literal AND the simulator code that emits it AND any per-intent
#: rule that maps a flag → Blocker code.
RiskFlag = Literal[
    # Pass flags
    "no_routing_loop",
    "no_isolation",
    "existing_sessions_intact",
    # Fail flags (caller turns these into Blockers)
    "routing_loop_introduced",
    "device_isolated",
    "existing_session_broken",
    # Informational
    "convergence_high",
    "blast_radius_large",
]


class SessionImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: str
    session: str
    was: str
    will_be: str


class RouteChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: str
    prefix: str
    next_hop: str | None = None


class SimulationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_flags: list[RiskFlag] = Field(default_factory=list)
    routes_added: list[RouteChange] = Field(default_factory=list)
    routes_removed: list[RouteChange] = Field(default_factory=list)
    sessions_impacted: list[SessionImpact] = Field(default_factory=list)
    convergence_estimate_s: int = Field(default=0, ge=0)

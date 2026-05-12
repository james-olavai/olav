"""Typed envelopes for the R-CAB-THREE-STAGE pipeline.

  Analyzer  ──DraftChangePlan──▶  Sim  ──CabTcf──▶  Lab
            ◀──RejectionReport──      ◀──LabRejectionReport──

Each envelope is Pydantic v2 + yaml-roundtrippable. The schemas are
the contract between sub-agents; validation errors here become REJECT
envelopes downstream rather than silent partial state. See
``dev_docs/75. CAB_THREE_STAGE_PIPELINE_AND_HARDCODING_REMOVAL.md``.
"""

from .draft import DraftChangePlan, SupportedIntent
from .facts import DeviceFact, FactsEnvelope, TopologyEdge
from .feasibility import Blocker, FeasibilityVerdict, SuggestedAlternative
from .rejection import DEFAULT_MAX_RETRIES, LabRejectionReport, RejectionReport
from .sim_report import RiskFlag, RouteChange, SessionImpact, SimulationReport

__all__ = [
    "Blocker",
    "DEFAULT_MAX_RETRIES",
    "DeviceFact",
    "DraftChangePlan",
    "FactsEnvelope",
    "FeasibilityVerdict",
    "LabRejectionReport",
    "RejectionReport",
    "RiskFlag",
    "RouteChange",
    "SessionImpact",
    "SimulationReport",
    "SuggestedAlternative",
    "SupportedIntent",
    "TopologyEdge",
]

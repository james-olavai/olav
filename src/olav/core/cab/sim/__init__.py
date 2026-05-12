"""Sim — the Python deterministic stage of the three-stage CAB pipeline.

Owns:
  * Per-intent feasibility rules (``sim.feasibility.*``) — read a
    DraftChangePlan + FactsEnvelope, return a FeasibilityVerdict.
  * networkx simulation (``sim.simulator``, Day 4) — runs the proposed
    change against an in-memory graph; reports SimulationReport.
  * Per-intent rendering (``sim.render.*``, Day 4) — turns a draft
    + facts into a CabTcf spec.
  * Atomic finalize entry-point (``sim.finalize``, Day 4) — the
    single function the orchestrator calls: draft.yaml in,
    spec.tcf.yaml OR rejection_sim.yaml out.

Sim NEVER writes prose, NEVER hand-codes CLI from an LLM call,
NEVER consults an LLM. Everything here is deterministic Python.
See ``dev_docs/75. CAB_THREE_STAGE_PIPELINE_AND_HARDCODING_REMOVAL.md``.
"""

---
name: sim
agent_type: api  # skill-script only; no LLM in the loop
# R-CAB-THREE-STAGE Day 4 2026-05-12 (dev_docs/75):
# Sim is the Python deterministic stage of the three-stage pipeline.
# It loads draft.yaml, runs per-intent feasibility, simulates the
# change on a networkx graph, and either renders a spec.tcf.yaml OR
# writes a structured rejection_sim.yaml. Pure Python; no LLM call.
# The sub-agent exists only so the orchestrator can dispatch via
# task("sim", "finalize", {"draft_path": ...}); the one tool below
# wraps the underlying olav.core.cab.sim.finalize entry-point.
thinking_mode: disabled
description: "Sim — Python deterministic stage. Reads a draft.yaml, runs feasibility + networkx simulation, writes either spec.tcf.yaml (on OK) or rejection_sim.yaml (on BLOCKED). Single tool: finalize_tcf(draft_path)."
tools:
  - finalize_tcf
metadata:
  version: 4.0.0
  type: agent
  network_isolation: "true"
  category: network-operations
  intents:
    - tcf_finalize
---

## Sim — finalize a draft

This sub-agent has exactly one tool: ``finalize_tcf(draft_path)``.

Call it with the draft path the Analyzer produced (e.g.
``exports/cab/<change_id>/draft.yaml``) and it returns one of:

* ``status: "ok"`` — spec.tcf.yaml written, hand off to lab via
  ``next_step.args.spec_path``.
* ``status: "rejected"`` — rejection_sim.yaml written, hand back to
  analyzer via ``next_step.args.rejection_path``.
* ``status: "error"`` — load/parse failure; surface to user.

There is NO multi-step reasoning here. One tool call → terminal envelope.

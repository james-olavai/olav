# ADR-0017: Memory-Layer Project Dimension (Multi-Tenancy)

**Status**: Accepted
**Date**: 2026-07-22

## Context

The presales domain (ADR-0016, dev_docs/100) runs N concurrent customer
engagements under one project root. Two hard requirements collide in the shared
LanceDB memory layer (dev_docs/100 §4.4/§4.5):

1. **Project facts must not leak across customers.** A fact distilled in
   customer A's session ("their core is dual-active N9K on 10.8.0.0/16") must
   never surface in customer B's session — a confidentiality breach, not merely
   a quality issue.
2. **Design *experience* must be shared.** Pattern-level knowledge ("dual-active
   designs need RTO confirmed before topology chapters") is the whole point of a
   cross-project memory and must remain recallable everywhere.

The L1/L2 capture loop distills session experience into `expert_knowledge`, and
`shared:*` scope is cross-project by design — so without a rule, customer A's
facts get injected into customer B's session. This is the first multi-tenancy
dimension the memory layer has needed.

Constraint: the platform core must not hardcode presales semantics
(repo-boundary rule). The dimension has to be **generic**.

## Decision

We add a generic **project dimension** to the memory layer, driven by a single
`OLAV_ACTIVE_PROJECT` environment signal that a domain (presales today) sets per
session. The platform core carries no presales-specific code; when the signal
is unset every code path is a no-op, so this is invisible to all existing
callers.

Two symmetric halves, both in `olav/core/memory/`:

1. **Recall predicate** (`filter_by_active_project`, wired into
   `AutoRecallMiddleware._gather_candidates`): with active project P, keep
   untagged records + records tagged `metadata.project == P`; exclude other
   projects. With **no** active project, keep only untagged records — project
   facts never leak into a non-project session.
2. **Capture policy** (`apply_project_capture_policy`, wired into
   `LanceDBStore.add_memory` behind a new `curator_provenance` flag): during an
   active-project session, non-`reflection` captures are tagged
   `metadata.project = P` and any `shared:*`/`org`/`global` scope is downgraded
   to a project-local scope. A project fact can never be written straight to a
   shared tier. `reflection` (generic failure constraints) stays cross-project.
   Promotion to a shared scope is HITL-only (`curator_provenance=True`).

Both are needed: the predicate alone does not stop a mis-scoped *write* from
leaking later; the write policy alone does not stop a stale tagged row from
surfacing in the wrong session.

## Consequences

### Positive

- Customer isolation is enforced on both read and write, generically.
- No change for any existing caller (no active project → no-op).
- Cross-project design experience (`reflection`, curator-promoted
  `expert_knowledge`) still flows.

### Negative / Costs

- A domain must remember to set `OLAV_ACTIVE_PROJECT`; if it doesn't, project
  facts simply aren't isolated (fail-open on isolation, but the recall predicate
  then also hides *nothing*, so no false confidentiality claim is made).
- `global`-scoped non-reflection captures during a project session become
  project-local — intended, but a behavioural change for any future domain that
  sets the env.

### Follow-ups

- ADR-0016 (presales domain), dev_docs/100 §4.4/§4.5.
- Governance pin: `tests/governance/test_presales_capture_policy.py` (capture
  never lands in shared:*/org without curator provenance; predicate fires from
  AutoRecall). Unit + integration: `tests/unit/test_memory_project_dimension.py`.
- Presales must export `OLAV_ACTIVE_PROJECT` at session start (project-switch =
  session-boundary event, dev_docs/100 §4.6) — wiring lands with the presales
  launch/`project use` flow.
- L4 trace-review/curator promotion should pass `curator_provenance=True` when
  promoting a reviewed memory to `shared:presales`.

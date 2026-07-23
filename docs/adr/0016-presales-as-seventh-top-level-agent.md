# ADR-0016: Presales as the Seventh Top-Level Agent

**Status**: Accepted
**Date**: 2026-07-22

## Context

`dev_docs/100. PRESALES_DOMAIN_DESIGN.md` (building on `dev_docs/98`) designs a
new **presales** domain: it ingests unstructured customer material (documents,
diagrams, meeting recordings), extracts structured topology + requirements,
drives collaborative HLD → LLD design generation, validates the design, and
produces per-engagement deliverables. This is temporally and directionally
distinct from the shipped domains:

| Domain | Time horizon | Input | Output |
|---|---|---|---|
| `netops` | Present | Live snapshots | Change plan CLI |
| `audit` | Present | DB snapshots | Health report |
| `presales` | **Future** | Customer docs + dialogue | HLD → LLD → validated design |

ADR-0004 requires an ADR arguing all four approval criteria before a new
top-level workspace agent (the `_EXPECTED_TOP_LEVEL_DIRS` set) may change.
This ADR records that argument for `presales`, and the delivery-model decision
(independent pip package, `olav-netops` precedent — `dev_docs/100` §1.3).

This ADR covers **step 1 (foundation)** of `dev_docs/100` §8: the package
skeleton, `presales.*` tables, the Tier-1 deterministic topology extractor, and
the `presales` orchestrator + `surveyor` sub-agent. The design (HLD/LLD)
sub-agents (`architect`, `engineer`, `publisher`) and the document-ingest /
vision / dossier layers land in later steps under the same domain.

## Decision

**We will add `presales` as the seventh top-level workspace agent**, delivered
as the independent pip package `olav-presales` (dependency direction
`olav-presales → olav` and `olav-presales → olav-netops`; never the reverse).

### ADR-0004 four criteria

1. **Distinct domain** — presales reasons over *future* designs from customer
   requirements; it is neither a `netops` operational task nor an `audit` of
   present state. Routing it under another orchestrator would conflate design
   intent with operational intent.
2. **Non-trivial tool surface** — the orchestrator owns `project_admin`; the
   `surveyor` sub-agent advertises `parse_diagram`, `review_extraction`,
   `save_topology` (≥3), with the design sub-agents adding more in later steps.
   Small-model caps hold: 1 sub-agent now (≤5), ≤5 scripts each, thin router.
3. **Independent lifecycle** — presales owns `.olav/presales/` (per-engagement
   customer data) and its own release cadence; it versions **independently** of
   the `olav`/`olav-netops` lockstep (different audience, greenfield deps such
   as Docling in later steps). It is therefore deliberately **exempt** from
   `tests/governance/test_package_version_parity.py` (dev_docs/100 Open Q2).
4. **Governance pin completeness** — this change lands atomically with:
   `_EXPECTED_TOP_LEVEL_DIRS += {presales}` + `olav.md` agents list
   (`test_v018_compliance.py`); the reachability gate scanning the presales
   authoritative workspace (`test_subagent_reachability.py` WORKSPACE_ROOTS);
   `ownership_manifest.yaml` rules for `olav-presales/**` + `.olav/presales/**`
   (+ `gen_gitignore --write`); the package integration test proving the
   surveyor scripts are reachable through `execute_skill_script`; and the CI
   `olav skill install olav-presales` step so the runtime workspace is deployed
   before the governance suite runs.

## Consequences

### Positive

- Design generation reuses shipped machinery: `presales.topology_*` is
  field-aligned with `netops` so `draw_topology` / networkx / Batfish / CLAB
  all consume it unchanged (dev_docs/100 §3.1).
- Customer data isolation is structural (`project_id` on every table;
  `.olav/presales/**` never committed).

### Negative / Costs

- A seventh agent widens the top-level routing surface; mitigated by the thin
  orchestrator + small-model caps.
- One platform-core touch beyond dev_docs/100's stated single change: the
  `execute_sql` schema allowlist gains `presales` (was hardcoded to
  `main`/`netops`).
- Independent versioning means the parity test needs a documented exemption
  (recorded here) rather than silent divergence.

### Follow-ups

- ADR-0004 (top-level agent policy); dev_docs/100 (domain design); dev_docs/98
  (HLD/LLD reasoning core).
- Mini-ADR for the memory-layer `project` dimension (dev_docs/100 §4.4) — a
  later step (§8 step 5), not part of this foundation.
- Governance tests pinning this decision: `test_v018_compliance.py`,
  `test_subagent_reachability.py`.
- Later steps: Docling document ingest, Tier-3 vision, HLD/LLD sub-agents,
  dossier projection, three-way archive purge (dev_docs/100 §8 steps 2–11).
